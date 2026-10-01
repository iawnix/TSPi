import { create_python_kernel_bridge } from "../../packages/research-agent-kernel/python_kernel_bridge.mjs";

const active_kernels = new Set();

export function create_test_research_kernel(options = {}) {
  const kernel = create_python_kernel_bridge(options);
  active_kernels.add(kernel);
  return kernel;
}

export async function close_test_research_kernels() {
  const kernels = [...active_kernels];
  active_kernels.clear();
  await Promise.all(kernels.map((kernel) => kernel.close()));
}
