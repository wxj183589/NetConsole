import { t } from './runtime'
import { meshBusinessZh } from './meshBusinessLabels'

export const meshBusinessText = (key: string): string => t(`mesh.business.${key}`, meshBusinessZh[key] || key)
