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
import { login as apiLogin, signup as apiSignup, updateUser as apiUpdateUser } from "@/lib/api";

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
  return localStorage.getItem(REMEMBER_KEY) === "true";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Use lazy initialization to avoid useEffect for initial load
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [rememberMe, setRememberMe] = useState<boolean>(() => isRemembered());

  // Save user to appropriate storage whenever it changes
  useEffect(() => {
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
  }, [user, rememberMe]);

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
    const updatedUser = await apiUpdateUser(user.id, data);
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
    isLoading: false, // With lazy initialization, we don't need loading state
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

