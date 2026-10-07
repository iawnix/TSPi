// bash is arbitrary code execution, including when used for Skill preparation.
// It must never inherit read-only admission from missing metadata.
export const NATIVE_TOOL_METADATA = Object.freeze({
  read: { authority: "host_read", effect: "read", phase: "orient" },
  system_prompt: { authority: "host_read", effect: "read", phase: "orient" },
  write: { authority: "execution_runtime", effect: "execution_control", phase: "prepare" },
  edit: { authority: "execution_runtime", effect: "execution_control", phase: "prepare" },
  bash: { authority: "execution_runtime", effect: "execution_control", phase: "prepare" },
});
