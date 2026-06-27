"use client";
import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

function GoogleCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, googleLogin } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    
    if (!code) {
      setError("No authorization code received.");
      return;
    }
    
    if (state === "login") {
      // Login flow
      googleLogin(code)
        .then(() => {
          router.push("/chatbot");
        })
        .catch(err => {
          setError(err instanceof Error ? err.message : "Failed to log in with Google");
        });
    } else {
      // Integration connection flow
      if (!user) {
        setError("You must be logged in to connect Google.");
        return;
      }
      
      fetch(`/api/auth/google/callback?code=${code}&state=${state || ""}`, {
        headers: {
          Authorization: `Bearer ${user.token}`
        }
      })
        .then(res => res.json())
        .then(data => {
          if (data.status === "success") {
            const connectedService = state && state !== "login" ? state : "google";
            router.push(`/integrations/integrations-page?success=${connectedService}_connected`);
          } else {
            setError(data.error || "Failed to connect Google account");
          }
        })
        .catch(err => {
          setError("Network error while connecting Google account");
        });
    }
  }, [searchParams, user, router, googleLogin]);

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center flex-col gap-4">
        <p className="text-red-500">{error}</p>
        <button 
          onClick={() => router.push("/settings")}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg"
        >
          Return to Settings
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center flex-col gap-4">
      <Loader2 className="animate-spin w-8 h-8 text-primary" />
      <p>Connecting your Google account...</p>
    </div>
  );
}

export default function GoogleCallbackPage() {
  return (
    <Suspense fallback={
      <div className="flex h-screen items-center justify-center flex-col gap-4">
        <Loader2 className="animate-spin w-8 h-8 text-primary" />
        <p>Loading...</p>
      </div>
    }>
      <GoogleCallbackContent />
    </Suspense>
  );
}
