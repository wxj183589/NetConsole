export type ConfirmType = 'INFO' | 'WARNING' | 'DANGER' | 'SECURITY' | 'DESTRUCTIVE'

export interface ConfirmOptions {
  type?: ConfirmType
  title: string
  message: string
  detail?: string
  confirmText?: string
  secondaryText?: string
  cancelText?: string
  acknowledgementText?: string
  requireAcknowledgement?: boolean
  closeOnEscape?: boolean
}
