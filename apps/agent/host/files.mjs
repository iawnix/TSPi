import { create_jsonl_subprocess_transport } from '../bridge/transport.mjs';
import { protocolError } from '../transport/host-client.mjs';

export const FILE_METHODS = Object.freeze(['files/list', 'files/stat', 'files/read', 'files/pin']);

/** File bytes are bounded range responses on the existing authenticated Link.
 * Reads do not attach a Pi session, wake a model, or start a public file server.
 */
export function createHostFiles({ workspace, python }) {
  let bridge;
  return {
    async handle(method, params) {
      if (!FILE_METHODS.includes(method)) throw protocolError('method_not_found', 'Unsupported file method');
      const allowed = new Set(['workspace_id', 'path', ...(method === 'files/list' ? ['limit', 'cursor'] : method === 'files/read' ? ['offset', 'length', 'expected_version'] : method === 'files/pin' ? ['expected_version'] : [])]);
      if (Object.keys(params).some(key => !allowed.has(key))) throw protocolError('invalid_params', 'Unsupported file parameter');
      const root = await workspace(params.workspace_id);
      bridge ||= create_jsonl_subprocess_transport({ command: python });
      try {
        return await bridge.request('workspace_files', { ...params, workspace_root: root, operation: method.slice(6) });
      } catch (error) {
        throw protocolError(error.code || 'file_unavailable', error.message);
      }
    },
    async close() { await bridge?.close(); },
  };
}
