import type { ComponentType } from "react";

/** "FileSearch" → "file-search"  (for display, matches tabler.io naming) */
function toKebab(name: string): string {
  return name.replace(/([A-Z])/g, (c, _, i) => (i > 0 ? "-" : "") + c.toLowerCase());
}

/** "file-search" → "FileSearch"  (palette key lookup) */
export function toPascal(name: string): string {
  return name.split("-").map(w => w ? w[0].toUpperCase() + w.slice(1) : "").join("");
}
import {
  IconActivity, IconAdjustments, IconArchive, IconBell, IconBook,
  IconBookmark, IconBrain, IconBriefcase, IconCalendar,
  IconChartBar, IconChartLine, IconChartPie,
  IconClipboard, IconClipboardCheck, IconClipboardList,
  IconClock, IconCloud, IconCode, IconCompass, IconCpu,
  IconDatabase, IconDownload, IconEdit,
  IconFile, IconFileAnalytics, IconFileCheck, IconFileDescription,
  IconFileSearch, IconFileText, IconFiles, IconFilter,
  IconFlag, IconFolder, IconFolderOpen, IconHash,
  IconHeart, IconHistory, IconHome, IconInbox,
  IconKey, IconLayout, IconLayoutDashboard,
  IconList, IconListCheck, IconListDetails,
  IconLock, IconMail, IconMessageCircle, IconMessages,
  IconPaperclip, IconPencil, IconPrinter, IconRefresh,
  IconRobot, IconSearch, IconServer,
  IconSettings, IconSettings2, IconShield,
  IconSparkles, IconStar, IconTag, IconTimeline,
  IconTool, IconUpload, IconUser, IconUsers,
  IconWand, IconZoom,
} from "@tabler/icons-react";

export type TablerNavIcon = ComponentType<{ size?: number; stroke?: number }>;

export const NAV_ICON_PALETTE: Record<string, TablerNavIcon> = {
  Activity:         IconActivity,
  Adjustments:      IconAdjustments,
  Archive:          IconArchive,
  Bell:             IconBell,
  Book:             IconBook,
  Bookmark:         IconBookmark,
  Brain:            IconBrain,
  Briefcase:        IconBriefcase,
  Calendar:         IconCalendar,
  ChartBar:         IconChartBar,
  ChartLine:        IconChartLine,
  ChartPie:         IconChartPie,
  Clipboard:        IconClipboard,
  ClipboardCheck:   IconClipboardCheck,
  ClipboardList:    IconClipboardList,
  Clock:            IconClock,
  Cloud:            IconCloud,
  Code:             IconCode,
  Compass:          IconCompass,
  Cpu:              IconCpu,
  Database:         IconDatabase,
  Download:         IconDownload,
  Edit:             IconEdit,
  File:             IconFile,
  FileAnalytics:    IconFileAnalytics,
  FileCheck:        IconFileCheck,
  FileDescription:  IconFileDescription,
  FileSearch:       IconFileSearch,
  FileText:         IconFileText,
  Files:            IconFiles,
  Filter:           IconFilter,
  Flag:             IconFlag,
  Folder:           IconFolder,
  FolderOpen:       IconFolderOpen,
  Hash:             IconHash,
  Heart:            IconHeart,
  History:          IconHistory,
  Home:             IconHome,
  Inbox:            IconInbox,
  Key:              IconKey,
  Layout:           IconLayout,
  LayoutDashboard:  IconLayoutDashboard,
  List:             IconList,
  ListCheck:        IconListCheck,
  ListDetails:      IconListDetails,
  Lock:             IconLock,
  Mail:             IconMail,
  MessageCircle:    IconMessageCircle,
  Messages:         IconMessages,
  Paperclip:        IconPaperclip,
  Pencil:           IconPencil,
  Printer:          IconPrinter,
  Refresh:          IconRefresh,
  Robot:            IconRobot,
  Search:           IconSearch,
  Server:           IconServer,
  Settings:         IconSettings,
  Settings2:        IconSettings2,
  Shield:           IconShield,
  Sparkles:         IconSparkles,
  Star:             IconStar,
  Tag:              IconTag,
  Timeline:         IconTimeline,
  Tool:             IconTool,
  Upload:           IconUpload,
  User:             IconUser,
  Users:            IconUsers,
  Wand:             IconWand,
  Zoom:             IconZoom,
};

/** All supported icon names in kebab-case (matches tabler.io display format). */
export const NAV_ICON_NAMES = Object.keys(NAV_ICON_PALETTE).map(toKebab).sort();
