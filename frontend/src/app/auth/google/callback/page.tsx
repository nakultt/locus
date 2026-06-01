"use client";
import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

function GoogleCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    
    if (!code) {
      setError("No authorization code received.");
      return;
    }
    
    if (!user) {
      setError("You must be logged in to connect Google.");
      return;
    }
    
    const token = localStorage.getItem("locus_auth_token");
    
    fetch(`http://localhost:8080/auth/google/callback?code=${code}`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })
      .then(res => res.json())
      .then(data => {
        if (data.status === "success") {
          router.push("/settings");
        } else {
          setError(data.error || "Failed to connect Google account");
        }
      })
      .catch(err => {
        setError("Network error while connecting Google account");
      });
  }, [searchParams, user, router]);

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
