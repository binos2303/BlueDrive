"use client";

import { createContext, type Dispatch, type SetStateAction } from "react";

// Folder details supply this context so navigation does not guess ownership from a URL.
export const SharedFolderContext = createContext<{
  folderId: number | null;
  setFolderId: Dispatch<SetStateAction<number | null>>;
} | null>(null);
