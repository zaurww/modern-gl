"""The entry point PyInstaller freezes beside the program (packaging/modern-gl.spec): the
assistant server `modern-gl-mcp.exe` an AI program starts (D83) — a console program, it
talks over stdin and stdout."""

from modern_gl.assistant.server import main

if __name__ == "__main__":
    main()
