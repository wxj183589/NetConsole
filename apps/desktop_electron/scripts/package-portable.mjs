import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

if (process.platform !== 'win32') {
  throw new Error('免安装版仅支持在 Windows 环境打包')
}

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(appRoot, '..', '..')
const packageJson = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8'))
const version = String(packageJson.version)
const outputRoot = resolve(projectRoot, 'dist', 'electron')
const unpackedRoot = resolve(outputRoot, 'win-unpacked')
const executable = resolve(unpackedRoot, 'NetConsole.exe')
const marker = resolve(unpackedRoot, 'portable.mode')
const archive = resolve(outputRoot, `NetConsole-${version}-portable.zip`)

if (existsSync(archive)) {
  throw new Error(`免安装版制品已存在，拒绝覆盖：${archive}`)
}

execFileSync('pnpm.cmd', ['run', 'package:prepare'], {
  cwd: appRoot,
  env: { ...process.env, NETCONSOLE_PORTABLE_BUILD: '1' },
  shell: true,
  stdio: 'inherit',
})

execFileSync('pnpm.cmd', ['exec', 'electron-builder', '--dir', '--win', '--x64'], {
  cwd: appRoot,
  env: process.env,
  shell: true,
  stdio: 'inherit',
})
if (!existsSync(executable)) {
  throw new Error(`Electron 免安装版目录缺少主程序：${executable}`)
}

writeFileSync(marker, 'NetConsole portable mode\n', { encoding: 'utf8', flag: 'w' })
const quotePowerShell = (value) => `'${value.replaceAll("'", "''")}'`
const command = [
  '$ErrorActionPreference = "Stop"',
  `Compress-Archive -Path ${quotePowerShell(`${unpackedRoot}\\*`)} -DestinationPath ${quotePowerShell(archive)} -CompressionLevel Optimal`,
].join('; ')
execFileSync('powershell.exe', [
  '-NoProfile',
  '-NonInteractive',
  '-ExecutionPolicy',
  'Bypass',
  '-Command',
  command,
], { stdio: 'inherit' })
console.log(`PORTABLE_ARTIFACT=${archive}`)
