const interfacePrefixes: Array<[RegExp, string]> = [
  [/^(?:HundredGigE|Hundred-?GigabitEthernet|100GigabitEthernet)\s*/i, '100GE'],
  [/^(?:FortyGigE|Forty-?GigabitEthernet|40GigabitEthernet)\s*/i, '40GE'],
  [/^(?:Twenty-?FiveGigE|Twenty-?Five-?GigabitEthernet|25GigabitEthernet)\s*/i, '25GE'],
  [/^(?:Ten-GigabitEthernet|TenGigabitEthernet|XGigabitEthernet)\s*/i, 'XGE'],
  [/^GigabitEthernet\s*/i, 'GE'],
]

export function displayInterfaceName(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  for (const [prefix, replacement] of interfacePrefixes) {
    if (prefix.test(text)) return text.replace(prefix, replacement)
  }
  return text
}
