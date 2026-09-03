import {
  CalendarDays,
  LayoutGrid,
  MessagesSquare,
  Plug,
  type LucideIcon,
} from "lucide-react";

/**
 * The signed-in destinations, in one place.
 *
 * The top bar, the mobile drawer and the command palette all read this array,
 * so they cannot disagree about what exists or what it is called. The version
 * this replaces listed the routes twice inside one file and got one of them
 * wrong: `/integrations/integrations-page` is not a route, so the Integrations
 * link in the sidebar — and the "Manage" button in Settings — both 404'd.
 *
 * Paths are deliberately unchanged from the old ones. `/integrations` is the
 * return target the backend redirects an OAuth round trip to
 * (`app/core/frontend_links.py`), and `/chatbot?id=` is a shareable deep link
 * into a conversation; renaming either buys a tidier URL and costs a broken
 * consent flow. The nav *labels* are what a user reads, and those are new.
 */
export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the command palette to disambiguate similar destinations. */
  hint: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/tasks",
    label: "Work",
    icon: LayoutGrid,
    hint: "Everything assigned to you and how far it has got",
  },
  {
    href: "/chatbot",
    label: "Chat",
    icon: MessagesSquare,
    hint: "Ask across your connected tools",
  },
  {
    href: "/scheduler",
    label: "Calendar",
    icon: CalendarDays,
    hint: "Conflicts, availability and fitting new work in",
  },
  {
    href: "/integrations",
    label: "Connections",
    icon: Plug,
    hint: "GitHub, Jira, Slack, Google and Linear",
  },
] as const;

/**
 * Whether a nav item is the current page.
 *
 * Prefix-matched rather than compared for equality so a future detail route
 * under a section keeps its parent lit; `/` is excluded because every path
 * starts with it.
 */
export const isActivePath = (pathname: string, href: string) =>
  pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
