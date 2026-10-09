import { create_python_runtime_bridge } from "../../packages/runtime-bridge/python_kernel_bridge.mjs";

const active_kernels = new Set();

export function create_test_research_memory(options = {}) {
  const kernel = create_python_runtime_bridge(options);
  active_kernels.add(kernel);
  return kernel;
}

export async function close_test_research_memorys() {
  const kernels = [...active_kernels];
  active_kernels.clear();
  await Promise.all(kernels.map((kernel) => kernel.close()));
}
