import { createContext, useContext } from "react";

export const TourContext = createContext<() => void>(() => {});
export const useTour = () => useContext(TourContext);

/** Current onboarding wizard version (API.md §2.1). */
export const ONBOARDING_VERSION = 1;
