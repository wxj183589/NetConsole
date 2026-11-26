import { parseSendString, type SendStringSegment } from './consoleButtonBar'

export type ConsoleRunScriptStep =
  | { type: 'SEND_STRING'; text: string }
  | { type: 'WAIT'; milliseconds: number }

export type ConsoleRunScript = {
  version: 1
  steps: ConsoleRunScriptStep[]
}

export type ValidatedConsoleRunScriptStep =
  | { type: 'SEND_STRING'; text: string; segments: SendStringSegment[] }
  | { type: 'WAIT'; milliseconds: number }

export type ValidatedConsoleRunScript = {
  version: 1
  steps: ValidatedConsoleRunScriptStep[]
  totalWaitMilliseconds: number
}

const MAX_SCRIPT_STEPS = 100
const MAX_WAIT_PER_STEP_MS = 60_000
const MAX_TOTAL_WAIT_MS = 600_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Validates the JSON-only Console script DSL. Scripts can write through the
 * existing Session API and wait. They cannot access JavaScript or host APIs.
 */
export function validateConsoleRunScript(value: unknown): ValidatedConsoleRunScript {
  if (!isRecord(value) || value.version !== 1 || Object.keys(value).length !== 2 || !Array.isArray(value.steps)) {
    throw new Error('Console 脚本必须使用版本 1 且包含步骤列表')
  }
  if (value.steps.length < 1 || value.steps.length > MAX_SCRIPT_STEPS) {
    throw new Error(`Console 脚本必须包含 1 至 ${MAX_SCRIPT_STEPS} 个步骤`)
  }

  let totalWaitMilliseconds = 0
  const steps = value.steps.map((rawStep, index): ValidatedConsoleRunScriptStep => {
    if (!isRecord(rawStep) || typeof rawStep.type !== 'string') {
      throw new Error(`Console 脚本第 ${index + 1} 步结构无效`)
    }
    if (rawStep.type === 'SEND_STRING') {
      if (Object.keys(rawStep).length !== 2 || typeof rawStep.text !== 'string') {
        throw new Error(`Console 脚本第 ${index + 1} 步只能包含动作类型和文本`)
      }
      const parsed = parseSendString(rawStep.text)
      totalWaitMilliseconds += parsed.segments.reduce(
        (wait, segment) => wait + (segment.kind === 'pause' ? segment.milliseconds : 0),
        0,
      )
      return { type: 'SEND_STRING', text: rawStep.text, segments: parsed.segments }
    }
    if (rawStep.type === 'WAIT') {
      if (Object.keys(rawStep).length !== 2) {
        throw new Error(`Console 脚本第 ${index + 1} 步只能包含动作类型和等待时长`)
      }
      if (!Number.isInteger(rawStep.milliseconds) || Number(rawStep.milliseconds) < 1 || Number(rawStep.milliseconds) > MAX_WAIT_PER_STEP_MS) {
        throw new Error(`Console 脚本第 ${index + 1} 步等待时长须为 1 至 ${MAX_WAIT_PER_STEP_MS} 毫秒的整数`)
      }
      totalWaitMilliseconds += Number(rawStep.milliseconds)
      return { type: 'WAIT', milliseconds: Number(rawStep.milliseconds) }
    }
    throw new Error(`Console 脚本第 ${index + 1} 步使用了不支持的动作`)
  })

  if (totalWaitMilliseconds > MAX_TOTAL_WAIT_MS) {
    throw new Error(`Console 脚本累计等待时间不能超过 ${MAX_TOTAL_WAIT_MS} 毫秒`)
  }
  return { version: 1, steps, totalWaitMilliseconds }
}

export function parseConsoleRunScriptJson(source: string): ValidatedConsoleRunScript {
  let value: unknown
  try {
    value = JSON.parse(source)
  } catch {
    throw new Error('Console 脚本必须是有效 JSON')
  }
  return validateConsoleRunScript(value)
}
