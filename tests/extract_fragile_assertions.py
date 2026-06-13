import re
from pathlib import Path

# Map of fragile assertions with their details
fragile_assertions = []

test_files = sorted(Path('.').glob('test_*.py'))

for test_file in test_files:
    content = test_file.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # Skip non-assertions
        if not ('assert' in stripped and 'in' in stripped):
            continue
        
        # Type 1: HTML string literals
        if 'in html' in line:
            match = re.search(r'assert\s+"([^"]+)"\s+in\s+html', line)
            if match:
                fragile_assertions.append({
                    'file': test_file.name,
                    'line': i,
                    'type': 'HTML字面量',
                    'snippet': match.group(1),
                    'context': 'HTML文件内容'
                })
        
        # Type 2: Source code text checks (reflection.md, *.py)
        if 'reflection.md' in line or ('read_text' in line and 'assert' in line and '"' in line):
            if 'reflection.md' in line:
                match = re.search(r'assert\s+"([^"]+)"\s+(?:not\s+)?in\s+reflection', line)
                if match:
                    fragile_assertions.append({
                        'file': test_file.name,
                        'line': i,
                        'type': '源码文本/Markdown',
                        'snippet': match.group(1),
                        'context': 'reflection.md文件内容'
                    })
            else:
                match = re.search(r'assert\s+"([^"]+)"\s+in\s+.*read_text', line)
                if match:
                    fragile_assertions.append({
                        'file': test_file.name,
                        'line': i,
                        'type': '源码文本',
                        'snippet': match.group(1),
                        'context': '源码文件内容'
                    })
        
        # Type 3: Shell script/command literals
        shell_indicators = ['$G16', '$INPUT', '$OUTPUT', '$SCRATCH', 'bash', 'nohup', 'mv -f', 'echo "', 'rm -f']
        if any(indicator in line for indicator in shell_indicators) and '"' in line and 'assert' in line:
            match = re.search(r'assert\s+["\']([^"\']*(?:\$[A-Z_]+|bash|nohup|< |> |mv |echo)[^"\']*)["\']', line)
            if match:
                fragile_assertions.append({
                    'file': test_file.name,
                    'line': i,
                    'type': 'shell脚本字面量',
                    'snippet': match.group(1),
                    'context': 'shell脚本文本'
                })

# Sort by file and line
fragile_assertions.sort(key=lambda x: (x['file'], x['line']))

# Print with Chinese formatting
for item in fragile_assertions:
    print(f"{item['file']}:{item['line']}")
    print(f"  类型: {item['type']}")
    print(f"  锁死的字符串: {item['snippet'][:70]}")
    print(f"  实现细节: {item['context']}")
    print()

print(f"\n总计找到 {len(fragile_assertions)} 处脆弱断言")
