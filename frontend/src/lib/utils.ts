import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// column_name -> "Column name" (mirrors the old Streamlit UI's _label helper)
export function formatLabel(column: string): string {
  const spaced = column.replace(/_/g, " ")
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function formatValue(value: unknown): string {
  if (typeof value === "boolean") return String(value)
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString("en-GB")
      : value.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  return String(value)
}
