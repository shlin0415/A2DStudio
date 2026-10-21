import { Unzip, UnzipInflate, UnzipPassThrough, zip } from 'fflate'
import {
  A2D_PROJECT_MAX_ARCHIVE_BYTES,
  A2D_PROJECT_MAX_ENTRIES,
  A2D_PROJECT_MAX_ENTRY_BYTES,
  A2D_PROJECT_MAX_EXPANDED_BYTES,
  A2D_PROJECT_MAX_MANIFEST_BYTES,
  nextProjectByteCount,
} from './a2d-project-format'

const END_OF_CENTRAL_DIRECTORY = 0x06054b50
const CENTRAL_DIRECTORY_ENTRY = 0x02014b50
const LOCAL_FILE_HEADER = 0x04034b50
const MAX_ZIP_COMMENT_BYTES = 0xffff
const ALLOWED_ZIP_FLAGS = 0x0006 | 0x0008 | 0x0800

interface ZipEntryMetadata {
  name: string
  compression: number
  compressedSize: number
  expandedSize: number
  checksum: number
  localHeaderOffset: number
  flags: number
}

function readUint16(view: DataView, offset: number): number {
  return view.getUint16(offset, true)
}

function readUint32(view: DataView, offset: number): number {
  return view.getUint32(offset, true)
}

function decodeArchiveName(bytes: Uint8Array): string {
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
}

function isAllowedArchiveName(name: string): boolean {
  return name === 'project.json'
    || /^assets\/(audio|backgrounds|images|music|references|avatars)\/[a-z0-9][a-z0-9._-]{0,127}$/.test(name)
}

async function readCentralDirectory(file: File): Promise<Map<string, ZipEntryMetadata>> {
  if (file.size > A2D_PROJECT_MAX_ARCHIVE_BYTES) throw new Error('项目压缩包超过 512 MiB 限制')
  if (file.size < 22) throw new Error('项目压缩包损坏或无法读取')

  const tailStart = Math.max(0, file.size - (22 + MAX_ZIP_COMMENT_BYTES))
  const tail = new Uint8Array(await file.slice(tailStart).arrayBuffer())
  const tailView = new DataView(tail.buffer, tail.byteOffset, tail.byteLength)
  const endRecordOffset = findEndRecord(tail, tailView)
  const endRecordAbsoluteOffset = tailStart + endRecordOffset
  if (readUint16(tailView, endRecordOffset + 20) !== 0) throw new Error('不支持带注释的项目压缩包')
  const diskNumber = readUint16(tailView, endRecordOffset + 4)
  const centralDiskNumber = readUint16(tailView, endRecordOffset + 6)
  const diskEntryCount = readUint16(tailView, endRecordOffset + 8)
  const entryCount = readUint16(tailView, endRecordOffset + 10)
  const centralSize = readUint32(tailView, endRecordOffset + 12)
  const centralOffset = readUint32(tailView, endRecordOffset + 16)
  if (diskNumber !== 0 || centralDiskNumber !== 0 || diskEntryCount !== entryCount) throw new Error('不支持分卷项目压缩包')
  if (entryCount > A2D_PROJECT_MAX_ENTRIES) throw new Error('项目压缩包条目数量超过限制')
  if (centralSize > 1024 * 1024) throw new Error('项目压缩包中央目录超过 1 MiB 限制')
  if (centralOffset + centralSize !== endRecordAbsoluteOffset) throw new Error('项目压缩包中央目录边界无效')

  const centralBytes = new Uint8Array(await file.slice(centralOffset, centralOffset + centralSize).arrayBuffer())
  const entries = parseCentralEntries(centralBytes, entryCount, centralOffset)
  await validateLocalHeaders(file, entries, centralOffset)
  return entries
}

function findEndRecord(tail: Uint8Array, view: DataView): number {
  for (let offset = tail.length - 22; offset >= 0; offset -= 1) {
    if (readUint32(view, offset) !== END_OF_CENTRAL_DIRECTORY) continue
    const commentLength = readUint16(view, offset + 20)
    if (offset + 22 + commentLength === tail.length) return offset
  }
  throw new Error('项目压缩包缺少结束目录')
}

function parseCentralEntries(bytes: Uint8Array, entryCount: number, centralOffset: number): Map<string, ZipEntryMetadata> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const entries = new Map<string, ZipEntryMetadata>()
  let cursor = 0
  let declaredExpandedBytes = 0
  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > bytes.length || readUint32(view, cursor) !== CENTRAL_DIRECTORY_ENTRY) {
      throw new Error('项目压缩包中央目录记录无效')
    }
    const flags = readUint16(view, cursor + 8)
    const compression = readUint16(view, cursor + 10)
    const checksum = readUint32(view, cursor + 16)
    const compressedSize = readUint32(view, cursor + 20)
    const expandedSize = readUint32(view, cursor + 24)
    const nameLength = readUint16(view, cursor + 28)
    const extraLength = readUint16(view, cursor + 30)
    const commentLength = readUint16(view, cursor + 32)
    const startDisk = readUint16(view, cursor + 34)
    const localHeaderOffset = readUint32(view, cursor + 42)
    const recordEnd = cursor + 46 + nameLength + extraLength + commentLength
    if (recordEnd > bytes.length || startDisk !== 0) throw new Error('项目压缩包目录记录不完整')
    if (extraLength !== 0 || commentLength !== 0) throw new Error('项目压缩包包含不支持的扩展元数据')
    if (compressedSize === 0xffffffff || expandedSize === 0xffffffff || localHeaderOffset === 0xffffffff) {
      throw new Error('暂不支持 ZIP64 项目压缩包')
    }
    if ((flags & 1) !== 0) throw new Error('不支持加密的项目压缩包')
    if (compression !== 0 && compression !== 8) throw new Error('项目压缩包包含不支持的压缩方式')
    if ((flags & ~ALLOWED_ZIP_FLAGS) !== 0) throw new Error('项目压缩包包含不支持的压缩标记')

    let name: string
    try {
      name = decodeArchiveName(bytes.subarray(cursor + 46, cursor + 46 + nameLength))
    } catch {
      throw new Error('项目压缩包文件名不是有效 UTF-8')
    }
    if (!isAllowedArchiveName(name)) throw new Error(`项目压缩包包含非法路径：${name}`)
    if (entries.has(name)) throw new Error(`项目压缩包包含重复路径：${name}`)
    if (name === 'project.json' && expandedSize > A2D_PROJECT_MAX_MANIFEST_BYTES) throw new Error('project.json 超过 10 MiB 限制')
    if (name !== 'project.json' && expandedSize > A2D_PROJECT_MAX_ENTRY_BYTES) throw new Error(`项目资源超过 128 MiB 限制：${name}`)
    declaredExpandedBytes = nextProjectByteCount(declaredExpandedBytes, expandedSize, A2D_PROJECT_MAX_EXPANDED_BYTES, 'archive expanded bytes')
    if (localHeaderOffset >= centralOffset) throw new Error('项目压缩包本地文件头偏移无效')
    entries.set(name, {
      name, compression, compressedSize, expandedSize, checksum, localHeaderOffset, flags,
    })
    cursor = recordEnd
  }
  if (cursor !== bytes.length) throw new Error('项目压缩包中央目录包含额外数据')
  return entries
}

async function validateLocalHeaders(file: File, entries: Map<string, ZipEntryMetadata>, centralOffset: number): Promise<void> {
  const ordered = [...entries.values()].sort((left, right) => left.localHeaderOffset - right.localHeaderOffset)
  let previousEnd = 0
  for (const entry of ordered) {
    if (entry.localHeaderOffset !== previousEnd) throw new Error('项目压缩包包含未索引的数据区域')
    const headerBytes = new Uint8Array(await file.slice(entry.localHeaderOffset, entry.localHeaderOffset + 30).arrayBuffer())
    if (headerBytes.byteLength !== 30) throw new Error(`本地文件头缺失：${entry.name}`)
    const header = new DataView(headerBytes.buffer, headerBytes.byteOffset, headerBytes.byteLength)
    if (readUint32(header, 0) !== LOCAL_FILE_HEADER) throw new Error(`本地文件头无效：${entry.name}`)
    const flags = readUint16(header, 6)
    const compression = readUint16(header, 8)
    const nameLength = readUint16(header, 26)
    const extraLength = readUint16(header, 28)
    const dataOffset = entry.localHeaderOffset + 30 + nameLength + extraLength
    if (flags !== entry.flags || compression !== entry.compression || extraLength !== 0 || dataOffset > centralOffset) {
      throw new Error(`本地文件头元数据不一致：${entry.name}`)
    }
    if ((flags & 8) === 0 && (
      readUint32(header, 14) !== entry.checksum
      || readUint32(header, 18) !== entry.compressedSize
      || readUint32(header, 22) !== entry.expandedSize
    )) throw new Error(`本地文件头大小或 CRC 不一致：${entry.name}`)
    const compressedDataEnd = dataOffset + entry.compressedSize
    const descriptorLength = (flags & 8) !== 0
      ? await validateDataDescriptor(file, compressedDataEnd, entry, centralOffset)
      : 0
    const endOffset = compressedDataEnd + descriptorLength
    if (endOffset > centralOffset) throw new Error(`项目压缩包数据越过中央目录：${entry.name}`)
    const localNameBytes = new Uint8Array(await file.slice(entry.localHeaderOffset + 30, entry.localHeaderOffset + 30 + nameLength).arrayBuffer())
    if (decodeArchiveName(localNameBytes) !== entry.name) throw new Error(`本地文件名与中央目录不一致：${entry.name}`)
    previousEnd = endOffset
  }
  if (previousEnd !== centralOffset) throw new Error('项目压缩包中央目录前包含未索引的数据')
}

async function validateDataDescriptor(
  file: File,
  offset: number,
  entry: ZipEntryMetadata,
  centralOffset: number,
): Promise<number> {
  const descriptorBytes = new Uint8Array(await file.slice(offset, offset + 16).arrayBuffer())
  const descriptor = new DataView(descriptorBytes.buffer, descriptorBytes.byteOffset, descriptorBytes.byteLength)
  const hasSignature = descriptorBytes.byteLength >= 16
    && readUint32(descriptor, 0) === 0x08074b50
    && descriptorMatches(descriptor, 4, entry)
  const valueOffset = hasSignature ? 4 : 0
  const descriptorLength = hasSignature ? 16 : 12
  if (offset + descriptorLength > centralOffset || descriptorBytes.byteLength < descriptorLength) {
    throw new Error(`项目压缩包数据描述符缺失：${entry.name}`)
  }
  if (!descriptorMatches(descriptor, valueOffset, entry)) throw new Error(`项目压缩包数据描述符与中央目录不一致：${entry.name}`)
  return descriptorLength
}

function descriptorMatches(view: DataView, offset: number, entry: ZipEntryMetadata): boolean {
  return readUint32(view, offset) === entry.checksum
    && readUint32(view, offset + 4) === entry.compressedSize
    && readUint32(view, offset + 8) === entry.expandedSize
}

const CRC32_TABLE = buildCrc32Table()

function buildCrc32Table(): Uint32Array {
  const table = new Uint32Array(256)
  for (let index = 0; index < table.length; index += 1) {
    let value = index
    for (let bit = 0; bit < 8; bit += 1) value = (value & 1) === 1 ? (value >>> 1) ^ 0xedb88320 : value >>> 1
    table[index] = value >>> 0
  }
  return table
}

function updateCrc32(checksum: number, bytes: Uint8Array): number {
  let value = checksum
  for (const byte of bytes) {
    const tableValue = CRC32_TABLE[(value ^ byte) & 0xff] ?? 0
    value = (tableValue ^ (value >>> 8)) >>> 0
  }
  return value
}

function createEntryCollector(
  metadata: ZipEntryMetadata,
  output: Map<string, Uint8Array>,
  actualSize: { total: number },
): (error: Error | null, chunk: Uint8Array, final: boolean) => void {
  const bytes = new Uint8Array(metadata.expandedSize)
  let size = 0
  let checksum = 0xffffffff
  return (error, chunk, final) => {
    if (error) throw error
    if (chunk.byteLength > 0) {
      size = nextProjectByteCount(size, chunk.byteLength, metadata.expandedSize, metadata.name)
      actualSize.total = nextProjectByteCount(actualSize.total, chunk.byteLength, A2D_PROJECT_MAX_EXPANDED_BYTES, 'archive expanded bytes')
      checksum = updateCrc32(checksum, chunk)
      bytes.set(chunk, size - chunk.byteLength)
    }
    if (!final) return
    if (size !== metadata.expandedSize || ((checksum ^ 0xffffffff) >>> 0) !== metadata.checksum) {
      throw new Error(`项目资源大小或 CRC 校验失败：${metadata.name}`)
    }
    output.set(metadata.name, bytes)
  }
}

/** Read ZIP files incrementally and verify central-directory sizes and CRCs before returning data. */
export async function readProjectArchive(file: File): Promise<Map<string, Uint8Array>> {
  const metadata = await readCentralDirectory(file)
  const output = new Map<string, Uint8Array>()
  const startedEntries = new Set<string>()
  const actualSize = { total: 0 }
  let failure: Error | null = null
  const unzip = new Unzip((entry) => {
    const expected = metadata.get(entry.name)
    if (!expected || startedEntries.has(entry.name)) {
      failure = new Error(`项目压缩包条目与目录不一致：${entry.name}`)
      return
    }
    if (entry.compression !== expected.compression
      || ((expected.flags & 8) === 0 && entry.size !== expected.compressedSize)
      || ((expected.flags & 8) === 0 && entry.originalSize !== expected.expandedSize)) {
      failure = new Error(`项目压缩包条目元数据不一致：${entry.name}`)
      return
    }
    startedEntries.add(entry.name)
    entry.ondata = createEntryCollector(expected, output, actualSize)
    try {
      entry.start()
    } catch (error) {
      failure = error instanceof Error ? error : new Error('无法解压项目资源')
    }
  })
  unzip.register(UnzipPassThrough)
  unzip.register(UnzipInflate)

  const reader = file.stream().getReader()
  let readBytes = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      readBytes = nextProjectByteCount(readBytes, value.byteLength, A2D_PROJECT_MAX_ARCHIVE_BYTES, 'archive bytes')
      unzip.push(value)
      if (failure) throw failure
    }
    unzip.push(new Uint8Array(), true)
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error instanceof Error ? error : new Error('项目压缩包损坏或无法读取')
  } finally {
    reader.releaseLock()
  }
  if (failure) throw failure
  if (startedEntries.size !== metadata.size || output.size !== metadata.size) throw new Error('项目压缩包条目不完整')
  return output
}

/** Build a ZIP from already-validated portable project entries. */
export function writeProjectArchive(files: Record<string, Uint8Array>): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    zip(files, { level: 6 }, (error, archive) => {
      if (error) reject(error)
      else resolve(archive)
    })
  })
}
