import React from 'react'
import {
  ArrowsClockwise,
  ArrowsLeftRight,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Buildings,
  CaretRight,
  Certificate,
  ChartBar,
  ChatCircle,
  Check,
  CheckCircle,
  ClipboardText,
  Clock,
  Copy,
  DownloadSimple,
  Eye,
  EyeSlash,
  FileArrowDown,
  FileText,
  Fire,
  FolderSimple,
  FlowArrow,
  GearSix,
  Globe,
  House,
  Image as PhosphorImage,
  Key,
  Lightbulb,
  Lightning,
  LinkSimple,
  List,
  Lock,
  MagnifyingGlass,
  MapPin,
  Moon,
  Package,
  PencilSimple,
  PenNib,
  Plus,
  Prohibit,
  PuzzlePiece,
  Quotes,
  Robot,
  RocketLaunch,
  Scales,
  Scroll,
  SealCheck,
  ShieldCheck,
  ShieldChevron,
  Sparkle,
  Star,
  Sun,
  Timer,
  Trash,
  UploadSimple,
  Users,
  Warning,
  X,
  XCircle,
} from '@phosphor-icons/react'

/** 统一的图标名称表：业务语义 → Phosphor 图标。 */
export type IconName =
  | 'scales'
  | 'lightning'
  | 'search'
  | 'chart'
  | 'package'
  | 'refresh'
  | 'trash'
  | 'edit'
  | 'download'
  | 'scroll'
  | 'file'
  | 'clipboard'
  | 'image'
  | 'sign'
  | 'buildings'
  | 'globe'
  | 'idea'
  | 'launch'
  | 'lock'
  | 'folder'
  | 'users'
  | 'pin'
  | 'chat'
  | 'link'
  | 'gear'
  | 'star'
  | 'arrow-down'
  | 'arrow-right'
  | 'arrow-left'
  | 'check'
  | 'close'
  | 'warning'
  | 'check-circle'
  | 'x-circle'
  | 'eye'
  | 'eye-slash'
  | 'upload'
  | 'plus'
  | 'home'
  | 'list'
  | 'seal'
  | 'certificate'
  | 'key'
  | 'shield'
  | 'swap'
  | 'flow'
  | 'caret-right'
  | 'copy'
  | 'puzzle'
  | 'robot'
  | 'quote'
  | 'file-download'
  | 'shield-chevron'
  | 'sparkle'
  | 'calendar'
  | 'clock'
  | 'fire'
  | 'paperclip'
  | 'prohibit'
  | 'dots'
  | 'moon'
  | 'sun'

const iconMap: Record<IconName, React.ComponentType<{ size?: number; color?: string; className?: string }>> = {
  scales: Scales,
  lightning: Lightning,
  search: MagnifyingGlass,
  chart: ChartBar,
  package: Package,
  refresh: ArrowsClockwise,
  trash: Trash,
  edit: PencilSimple,
  download: DownloadSimple,
  scroll: Scroll,
  file: FileText,
  clipboard: ClipboardText,
  image: PhosphorImage,
  sign: PenNib,
  buildings: Buildings,
  globe: Globe,
  idea: Lightbulb,
  launch: RocketLaunch,
  lock: Lock,
  folder: FolderSimple,
  users: Users,
  pin: MapPin,
  chat: ChatCircle,
  link: LinkSimple,
  gear: GearSix,
  star: Star,
  'arrow-down': ArrowDown,
  'arrow-right': ArrowRight,
  'arrow-left': ArrowLeft,
  check: Check,
  close: X,
  warning: Warning,
  'check-circle': CheckCircle,
  'x-circle': XCircle,
  eye: Eye,
  'eye-slash': EyeSlash,
  upload: UploadSimple,
  plus: Plus,
  home: House,
  list: List,
  seal: SealCheck,
  certificate: Certificate,
  key: Key,
  shield: ShieldCheck,
  swap: ArrowsLeftRight,
  flow: FlowArrow,
  'caret-right': CaretRight,
  copy: Copy,
  puzzle: PuzzlePiece,
  robot: Robot,
  quote: Quotes,
  'file-download': FileArrowDown,
  'shield-chevron': ShieldChevron,
  sparkle: Sparkle,
  calendar: Clock,
  clock: Clock,
  fire: Fire,
  paperclip: Copy,
  prohibit: Prohibit,
  dots: List,
  moon: Moon,
  sun: Sun,
}

interface IconProps {
  name: IconName
  size?: number
  color?: string
  className?: string
  /** 装饰性图标默认对读屏隐藏；功能性图标应通过按钮/标签的 aria-label 提供名称。 */
  decorative?: boolean
}

export const Icon: React.FC<IconProps> = ({
  name,
  size = 16,
  color,
  className,
  decorative = true,
}) => {
  const Cmp = iconMap[name]
  return <Cmp size={size} color={color} className={className} aria-hidden={decorative} />
}
