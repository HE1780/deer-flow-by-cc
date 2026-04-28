/**
 * Tri-state encoder/decoder for fields whose backend value is one of:
 *   null         → "inherit / use all"
 *   []           → "explicitly all off"
 *   ["a", ...]   → "whitelist"
 *
 * Used by the agent edit page for both `tool_groups` and `skills`.
 */

export interface TriState {
  useAll: boolean;
  selected: string[];
}

export function decodeTriState(value: string[] | null | undefined): TriState {
  if (value === null || value === undefined) {
    return { useAll: true, selected: [] };
  }
  return { useAll: false, selected: [...value] };
}

export function encodeTriState(state: TriState): string[] | null {
  if (state.useAll) return null;
  return [...state.selected];
}

/** Skill values may be `name` or `name@version`. The base name is the part
 *  before the first `@`. Used as the checkbox match key. */
export function skillBaseName(value: string): string {
  const idx = value.indexOf("@");
  return idx === -1 ? value : value.slice(0, idx);
}

/**
 * Toggle a skill in/out of the selected list, matching by base name so
 * `name@version` strings survive the round trip.
 */
export function toggleSkillSelection(
  selected: string[],
  baseName: string,
  initialPin?: string,
): string[] {
  const idx = selected.findIndex((v) => skillBaseName(v) === baseName);
  if (idx >= 0) {
    return [...selected.slice(0, idx), ...selected.slice(idx + 1)];
  }
  return [...selected, initialPin ?? baseName];
}
