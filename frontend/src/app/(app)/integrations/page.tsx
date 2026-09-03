import IntegrationsView from "@/features/integrations/integrations-view";

/**
 * Labelled "Connections" throughout the interface, but the path stays
 * `/integrations`: this is the URL the backend redirects an OAuth round trip
 * back to (`app/core/frontend_links.py`), carrying its outcome in the query
 * string. Renaming it buys a tidier address and costs a broken consent flow.
 */
export default function IntegrationsPage() {
  return <IntegrationsView />;
}
