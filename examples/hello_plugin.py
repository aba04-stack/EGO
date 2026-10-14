"""Пример плагина AlterEgo Training Hub.

Скопируйте файл в папку «plugins» каталога приложения
(например ~/.config/AlterEgoTrainingHub/plugins/) и нажмите
«Перезагрузить плагины» в Настройках → «Платформа: клавиши и плагины».

Плагин добавляет агенту два инструмента: чтение (hello_tool) и мутацию
(hello_write, требует подтверждения).
"""


def _greet(args):
    name = str(args.get("name") or "мир")
    return {"ok": True, "text": f"Привет, {name}!"}


def _note(args):
    return {"ok": True, "note": f"записано: {args.get('text', '')}"}


PLUGIN = {
    "id": "hello",
    "name": "Hello",
    "version": "1.0",
    "description": "Пример плагина: инструменты приветствия и заметок.",
    # "trusted": True,  # раскомментируйте, чтобы выполнять в процессе;
    # без флага плагин работает в песочнице (см. README).
    "tools": {
        "hello_tool": {
            "schema": {
                "type": "function",
                "function": {
                    "name": "hello_tool",
                    "description": "Поздороваться по имени.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Имя"},
                        },
                        "required": [],
                    },
                },
            },
            "handler": _greet,
            "mutation": False,
        },
        "hello_write": {
            "schema": {
                "type": "function",
                "function": {
                    "name": "hello_write",
                    "description": "Оставить заметку (пример мутации).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Текст"},
                        },
                        "required": ["text"],
                    },
                },
            },
            "handler": _note,
            "mutation": True,
        },
    },
}
