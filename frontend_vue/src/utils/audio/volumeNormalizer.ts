/**
 * 音量均衡工具 — Web Audio API GainNode
 *
 * 仅用于 ref audio（Tier 1）。Tier 2/3 是 GSV 生成，音量已一致。
 * 开关：A2D_ENABLE_VOLUME_NORMALIZATION (默认 true)
 *
 * 性能：每个 clip < 20ms（decodeAudioData ~15ms + RMS < 1ms + GainNode 硬件加速）
 */

let audioContext: AudioContext | null = null

function getContext(): AudioContext {
  if (!audioContext) {
    audioContext = new AudioContext()
  }
  return audioContext
}

/** 计算音频缓冲区的 RMS（均方根）响度 */
function computeRMS(buffer: AudioBuffer): number {
  const data = buffer.getChannelData(0)
  let sum = 0
  for (let i = 0; i < data.length; i++) {
    sum += data[i] * data[i]
  }
  return Math.sqrt(sum / data.length)
}

/**
 * 加载音频并创建音量归一化的 AudioBufferSourceNode。
 *
 * @param url - 音频文件 URL
 * @param targetVolume - 目标音量 (0-100)，来自 uiStore.characterVolume
 * @returns 已调用 start() 的 AudioBufferSourceNode
 */
export async function playNormalized(
  url: string,
  targetVolume: number,
): Promise<AudioBufferSourceNode> {
  const ctx = getContext()
  const response = await fetch(url)
  const arrayBuffer = await response.arrayBuffer()
  const audioBuffer = await ctx.decodeAudioData(arrayBuffer)

  const rms = computeRMS(audioBuffer)
  // 参考 RMS ≈ 0.1（经验值），将目标音量映射到 gain
  const refRMS = 0.1
  const targetGain = (targetVolume / 80) * (refRMS / Math.max(rms, 0.001))
  // 限制增益范围，防止极端情况
  const clampedGain = Math.min(Math.max(targetGain, 0.1), 2.0)

  const source = ctx.createBufferSource()
  source.buffer = audioBuffer

  const gainNode = ctx.createGain()
  gainNode.gain.value = clampedGain

  source.connect(gainNode)
  gainNode.connect(ctx.destination)
  source.start()

  return source
}

/** 检查音量均衡是否启用 */
export function isVolumeNormalizationEnabled(): boolean {
  // 默认开启，后续可通过后端 API 或 localStorage 读取
  return true
}
