"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MessageSquarePlus, PanelLeftClose, Search } from "lucide-react";
import { getUserConversations, type Conversation } from "@/lib/api";
import { useAuth } from "@/features/auth/auth-context";
import { Button, IconButton } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/surface";
import { formatFull } from "@/lib/datetime";
import { cn } from "@/lib/utils";

/**
 * The conversation list.
 *
 * This used to live in the global sidebar, which meant the task board, the
 * calendar, the connections page and settings all reserved a 256px column for
 * a list of chat threads none of them could use. It belongs to chat, so it
 * lives in chat: a rail beside the conversation on a wide screen, and a
 * drawer on a narrow one.
 */
export function useConversations() {
  const { user } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!user?.id) {
      setLoading(false);
      return;
    }
    try {
      const response = await getUserConversations();
      // Defaulted rather than trusted. A response missing this key — an older
      // backend, a proxy returning an error body with a 200 — put `undefined`
      // into state, and the header below calls `.find` on it, which took the
      // whole chat page down with a runtime error instead of showing an empty
      // rail. The list is decoration on the conversation; it must not be able
      // to break it.
      setConversations(response?.conversations ?? []);
    } catch {
      // A failed list costs the rail, never the conversation on screen.
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { conversations, loading, reload };
}

export function ConversationRail({
  conversations,
  loading,
  activeId,
  onPick,
  onCollapse,
  className,
}: {
  conversations: Conversation[];
  loading: boolean;
  activeId?: number;
  onPick?: () => void;
  onCollapse?: () => void;
  className?: string;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const filtered = query.trim()
    ? conversations.filter((c) =>
        c.title.toLowerCase().includes(query.trim().toLowerCase())
      )
    : conversations;

  const open = (id?: number) => {
    router.push(id ? `/chatbot?id=${id}` : "/chatbot");
    onPick?.();
  };

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="flex items-center gap-2 px-3 pt-3">
        <Button size="sm" className="flex-1" onClick={() => open()}>
          <MessageSquarePlus aria-hidden />
          New chat
        </Button>
        {onCollapse && (
          <IconButton
            label="Hide conversations"
            size="sm"
            variant="ghost"
            onClick={onCollapse}
            className="hidden lg:inline-flex"
          >
            <PanelLeftClose />
          </IconButton>
        )}
      </div>

      {/* Search appears only once there is enough to search. A filter box over
          three items is noise. */}
      {conversations.length > 6 && (
        <div className="px-3 pt-2">
          <Input
            type="search"
            inputSize="sm"
            icon={<Search aria-hidden />}
            aria-label="Filter conversations"
            placeholder="Filter"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {loading ? (
          <div className="space-y-1.5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-muted">
            {query.trim()
              ? `Nothing matches “${query.trim()}”.`
              : "No conversations yet. Ask something to start one."}
          </p>
        ) : (
          <ul className="space-y-0.5">
            {filtered.map((chat) => {
              const active = chat.id === activeId;
              return (
                <li key={chat.id}>
                  <button
                    type="button"
                    onClick={() => open(chat.id)}
                    aria-current={active ? "page" : undefined}
                    title={chat.title}
                    className={cn(
                      "w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors",
                      active
                        ? "bg-surface-3 font-medium text-ink"
                        : "text-muted hover:bg-surface-2 hover:text-ink"
                    )}
                  >
                    {chat.title}
                    {chat.updated_at && (
                      <span className="mt-0.5 block truncate text-xs font-normal text-subtle">
                        {formatFull(chat.updated_at)}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
