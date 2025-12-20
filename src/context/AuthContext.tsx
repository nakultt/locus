/**
 * Authentication Context
 * Provides user auth state and functions throughout the app
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import type { User } from "@/lib/api";
import { login as apiLogin, signup as apiSignup } from "@/lib/api";

// ============== Types ==============

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<User>;
  signup: (email: string, password: string, name?: string) => Promise<User>;
  logout: () => void;
}

// ============== Context ==============

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = "locus_user";

// ============== Provider ==============

function getStoredUser(): User | null {
  let stored = localStorage.getItem(STORAGE_KEY);
  if (!stored) {
    stored = sessionStorage.getItem(STORAGE_KEY);
  }
  if (stored) {
    try {
      return JSON.parse(stored);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Use lazy initialization to avoid useEffect for initial load
  const [user, setUser] = useState<User | null>(() => getStoredUser());

  // No automatic saving; only save in login based on rememberMe

  const login = async (email: string, password: string, rememberMe: boolean = true): Promise<User> => {
    const userData = await apiLogin(email, password);
    setUser(userData);
    // Store based on rememberMe
    if (rememberMe) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(userData));
    } else {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(userData));
    }
    return userData;
  };

  const signup = async (
    email: string,
    password: string,
    name?: string
  ): Promise<User> => {
    const userData = await apiSignup(email, password, name);
    setUser(userData);
    return userData;
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
  };

  const value: AuthContextType = {
    user,
    isLoading: false, // With lazy initialization, we don't need loading state
    isAuthenticated: !!user,
    login,
    signup,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ============== Hook ==============

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export default AuthContext;
