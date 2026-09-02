import { redirect } from "next/navigation";

/**
 * The PR agent dashboard became the task board. Kept as a redirect so existing
 * links and bookmarks do not break.
 */
export default function PrAgentPage() {
  redirect("/tasks");
}
