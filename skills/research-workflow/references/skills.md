# Skill resources

Pi loads installed Skill descriptors and the Agent reads their SKILL.md on demand. CoRAgent verifies installed resource digests. Use the actual Skill path supplied by Pi and resolve its relative references from that directory.

Read only listed resource names. A missing reference means the requested file does not exist at that Skill location; inspect its actual references list. Do not infer another Skill's folder from its topic. For reaction mapping open references/reaction_mapping.md under the chemical-input Skill directory.

An invalid tool argument or missing path is a correctable local error. Inspect the contract/path and retry; it does not establish that the research task is impossible. Separate software failures from scientific counter-evidence.

Discovery uses the English `SKILL.md`. `SKILL.zh-CN.md` is a translation and does not automatically replace the entrypoint based on user language. Read it explicitly when useful; respond in the user's requested language.
