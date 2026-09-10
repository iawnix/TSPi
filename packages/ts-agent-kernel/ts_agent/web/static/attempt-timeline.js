"use strict";

(function attachAttemptTimeline(global) {
  const PAGE_SIZE = 6;

  function project(value, options = {}) {
    const attempts = orderedRecords(value);
    const families = unique(attempts.map(familyId).filter(Boolean));
    const kinds = unique(attempts.map(row => string(row.attempt_kind) || "primary"));
    const states = unique(attempts.map(row => string(row.display_state) || "unknown"));
    const filters = {
      family: validChoice(options.family, families),
      kind: validChoice(options.kind, kinds),
      state: validChoice(options.state, states),
    };
    const filtered = attempts.filter(row => (
      (filters.family === "all" || familyId(row) === filters.family)
      && (filters.kind === "all" || (string(row.attempt_kind) || "primary") === filters.kind)
      && (filters.state === "all" || (string(row.display_state) || "unknown") === filters.state)
    ));
    const pageSize = positiveInteger(options.pageSize) || PAGE_SIZE;
    const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
    const page = Math.min(pageCount, positiveInteger(options.page) || 1);
    const offset = (page - 1) * pageSize;
    return {
      rows: filtered.slice(offset, offset + pageSize),
      total: filtered.length,
      page,
      pageCount,
      pageSize,
      filters,
      choices: { families, kinds, states },
    };
  }

  function pageForAttempt(value, options, intentId) {
    const attempts = orderedRecords(value);
    const view = project(attempts, { ...options, page: 1 });
    const matching = attempts.filter(row => (
      (view.filters.family === "all" || familyId(row) === view.filters.family)
      && (view.filters.kind === "all" || (string(row.attempt_kind) || "primary") === view.filters.kind)
      && (view.filters.state === "all" || (string(row.display_state) || "unknown") === view.filters.state)
    ));
    const index = matching.findIndex(row => string(row.intent_id) === string(intentId));
    return index < 0 ? null : Math.floor(index / view.pageSize) + 1;
  }

  function familyId(row) {
    return string(row?.family_root_id) || string(row?.intent_id);
  }

  function validChoice(value, choices) {
    const selected = string(value);
    return selected !== "all" && choices.includes(selected) ? selected : "all";
  }

  function positiveInteger(value) {
    const number = Number(value);
    return Number.isInteger(number) && number > 0 ? number : null;
  }

  function unique(values) {
    return [...new Set(values)].sort(naturalCompare);
  }

  function naturalCompare(left, right) {
    return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  }

  function records(value) {
    return Array.isArray(value) ? value.filter(row => row && typeof row === "object" && !Array.isArray(row)) : [];
  }

  function orderedRecords(value) {
    return records(value).slice().sort((left, right) => {
      const familyOrder = (Number(left.family_index) || Number.MAX_SAFE_INTEGER)
        - (Number(right.family_index) || Number.MAX_SAFE_INTEGER);
      return familyOrder || naturalCompare(string(left.intent_id), string(right.intent_id));
    });
  }

  function string(value) {
    return typeof value === "string" ? value : "";
  }

  global.TSAttemptTimeline = Object.freeze({ PAGE_SIZE, project, pageForAttempt });
})(window);
