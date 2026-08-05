export type ConfirmType = 'INFO' | 'WARNING' | 'DANGER' | 'SECURITY' | 'DESTRUCTIVE'

export interface ConfirmOptions {
  type?: ConfirmType
  title: string
  message: string
  highlight?: string
  detail?: string
  notice?: string
  width?: string
  confirmText?: string
  confirmLoadingText?: string
  secondaryText?: string
  cancelText?: string
  acknowledgementText?: string
  requireAcknowledgement?: boolean
  confirmationText?: string
  confirmationLabel?: string
  confirmationPlaceholder?: string
  closeOnEscape?: boolean
  onConfirm?: () => void | Promise<void>
}
