const PACKAGE_ROOT_ENV = "TSPI_PACKAGE_ROOT";

/**
 * Keep the TSPi package root available to the facet factory, but hide it while
 * Pi's built-in client facets are activated. The managed Pi patch uses this
 * variable as the opt-in for its status-only /sys_prompt command.
 */
export async function withTspiPackageRootHidden(callback) {
  if (typeof callback !== "function") throw new TypeError("callback must be a function");
  const hadValue = Object.prototype.hasOwnProperty.call(process.env, PACKAGE_ROOT_ENV);
  const previousValue = process.env[PACKAGE_ROOT_ENV];
  let restored = false;
  const restore = () => {
    if (restored) return;
    restored = true;
    if (hadValue && previousValue !== undefined) process.env[PACKAGE_ROOT_ENV] = previousValue;
    else delete process.env[PACKAGE_ROOT_ENV];
  };
  delete process.env[PACKAGE_ROOT_ENV];
  try {
    return await callback(restore);
  } finally {
    restore();
  }
}

export function createTspiPackageRootRestoreFacet(restore, dependency) {
  if (typeof restore !== "function") throw new TypeError("restore must be a function");
  if (!dependency || typeof dependency.id !== "string") throw new TypeError("dependency service is required");
  return {
    id: "@tspi/native-client-package-root-restore",
    setup(env) {
      env.use(dependency);
      env.onActivate(() => restore());
    },
  };
}
