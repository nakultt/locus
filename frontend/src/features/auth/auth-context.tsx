"use client";

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
import type { User, UserUpdate } from "@/lib/api";
import {
  login as apiLogin,
  onSessionExpired,
  signup as apiSignup,
  updateUser as apiUpdateUser,
} from "@/lib/api";

// ============== Types ==============

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<User>;
  signup: (email: string, password: string, name?: string) => Promise<User>;
  updateProfile: (data: UserUpdate) => Promise<User>;
  logout: () => void;
}

// ============== Context ==============

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = "locus_user";
const REMEMBER_KEY = "locus_remember";

// ============== Provider ==============

function getStoredUser(): User | null {
  // Next renders this provider on the server, where there is no storage to
  // read. Answering "nobody is signed in" there is correct: the real answer
  // lives in the browser and arrives on the hydration pass below.
  if (typeof window === "undefined") return null;

  // Check localStorage first (Remember Me was checked)
  const localStored = localStorage.getItem(STORAGE_KEY);
  if (localStored) {
    try {
      return JSON.parse(localStored);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }
  
  // Check sessionStorage (Remember Me was not checked, current session only)
  const sessionStored = sessionStorage.getItem(STORAGE_KEY);
  if (sessionStored) {
    try {
      return JSON.parse(sessionStored);
    } catch {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }
  
  return null;
}

function isRemembered(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(REMEMBER_KEY) === "true";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [rememberMe, setRememberMe] = useState<boolean>(false);

  /**
   * Whether the browser's stored session has been read yet.
   *
   * Under Vite this was not needed: `useState(() => getStoredUser())` ran once,
   * in the browser, before the first render. Next renders this component on the
   * server first, where there is no storage, so the first client render must
   * agree with the server's "signed out" markup or hydration fails — and
   * `ProtectedRoute` would bounce a signed-in user to /login before their
   * session was ever loaded. Everything waits on this flag instead.
   */
  const [isHydrated, setIsHydrated] = useState(false);

  useEffect(() => {
    setUser(getStoredUser());
    setRememberMe(isRemembered());
    setIsHydrated(true);
  }, []);

  // A 401 anywhere in the app means this session is dead -- the token expired,
  // or it names an account that no longer exists (a wiped database is the
  // common case in development). The API layer has already cleared storage;
  // dropping the user here is what makes ProtectedRoute redirect to /login
  // instead of leaving the UI signed in against a backend that refuses it.
  useEffect(() => onSessionExpired(() => setUser(null)), []);

  // Save user to appropriate storage whenever it changes.
  //
  // Held until the read above has happened. Without that guard this effect
  // fires on mount with the pre-hydration `null` and erases the very session
  // the effect above is in the middle of restoring.
  useEffect(() => {
    if (!isHydrated) return;

    if (user) {
      if (rememberMe) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
        localStorage.setItem(REMEMBER_KEY, "true");
        sessionStorage.removeItem(STORAGE_KEY);
      } else {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(user));
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(REMEMBER_KEY);
      }
    } else {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(REMEMBER_KEY);
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }, [user, rememberMe, isHydrated]);

  const login = async (
    email: string, 
    password: string,
    remember: boolean = false
  ): Promise<User> => {
    const userData = await apiLogin(email, password, remember);
    setRememberMe(remember);
    setUser(userData);
    return userData;
  };

  const signup = async (
    email: string,
    password: string,
    name?: string
  ): Promise<User> => {
    const userData = await apiSignup(email, password, name);
    // Default to session-only for signup
    setRememberMe(false);
    setUser(userData);
    return userData;
  };

  const updateProfile = async (data: UserUpdate): Promise<User> => {
    if (!user?.id) throw new Error("User not logged in");
    const updatedUser = await apiUpdateUser(data);
    setUser(updatedUser);
    return updatedUser;
  };

  const logout = () => {
    setUser(null);
    setRememberMe(false);
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(REMEMBER_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
  };

  const value: AuthContextType = {
    user,
    // True until the browser's stored session has been read. Consumers use
    // this to hold their render rather than treating "not yet known" as
    // "signed out".
    isLoading: !isHydrated,
    isAuthenticated: !!user,
    login,
    signup,
    updateProfile,
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

