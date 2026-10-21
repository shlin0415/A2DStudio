import { shallowReactive } from 'vue'

const importedAvatarUrls = shallowReactive(new Map<string, string>())
let activeProjectUrls: string[] = []

export function getProjectAvatarRegistryKey(scriptRoleKey: string, clothesName: string, emotion: string): string {
  return `${scriptRoleKey}\u0000${clothesName}\u0000${emotion}`
}

export function getImportedProjectAvatar(scriptRoleKey: string, clothesName: string, emotion: string): string | null {
  return importedAvatarUrls.get(getProjectAvatarRegistryKey(scriptRoleKey, clothesName, emotion)) || null
}

/** Replace package-owned URLs only after an import has successfully updated both stores. */
export function registerImportedProjectAssets(avatarUrls: Map<string, string>, objectUrls: string[]): void {
  const previousUrls = activeProjectUrls
  importedAvatarUrls.clear()
  for (const [key, url] of avatarUrls) importedAvatarUrls.set(key, url)
  activeProjectUrls = objectUrls
  previousUrls.forEach((url) => URL.revokeObjectURL(url))
}
