"use client";

import { createContext, useContext } from "react";

/** Lets cards inside messages send a follow-up to the agent ("Compare", "Price history"). */
export const AskContext = createContext<(text: string) => void>(() => {});

export const useAsk = () => useContext(AskContext);
