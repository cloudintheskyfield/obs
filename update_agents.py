import os
import re

files = [
    "src/agents/generator_agent.py",
    "src/agents/evaluator_agent.py",
    "src/agents/runner_agent.py",
    "src/agents/search_agent.py",
]

for file_path in files:
    with open(file_path, "r") as f:
        content = f.read()

    # The pattern we want to replace is the streaming loop
    # We want to insert `chunk_count` initialization and increment,
    # and extract thinking_content from raw_content.
    # Note that raw_content is built differently in different agents.
    
    # Actually, it might be safer to manually do multi_replace for each since they might be slightly different.
    pass

