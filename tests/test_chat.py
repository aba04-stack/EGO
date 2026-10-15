import time

from alterego_training_hub.chat import ChatMessage, ChatSession, ChatStore


def test_session_roundtrip_and_title(tmp_path):
    store = ChatStore(tmp_path / "chats")
    session = ChatSession()
    session.add("user", "Как починить тесты обучения?\nВторая строка")
    session.add("assistant", "Сначала прочитаю лог.")
    session.add("tool", '{"ok": true}', name="read_file", tool_call_id="call-1")
    store.save(session)

    loaded = store.load(session.id)
    assert loaded.title == "Как починить тесты обучения?"
    assert len(loaded.messages) == 3
    assert loaded.messages[2].name == "read_file"
    assert loaded.messages[2].tool_call_id == "call-1"

    listed = store.list_sessions()
    assert [item.id for item in listed] == [session.id]


def test_history_for_api_includes_tool_fields():
    session = ChatSession()
    session.add("user", "прочитай файл")
    session.add(
        "assistant", "",
        tool_calls=[{"id": "c1", "type": "function",
                     "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"}}],
    )
    session.add("tool", '{"ok": true}', name="read_file", tool_call_id="c1")
    history = session.history_for_api(system_prompt="system")
    assert history[0] == {"role": "system", "content": "system"}
    assert history[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert history[3]["role"] == "tool"
    assert history[3]["tool_call_id"] == "c1"


def test_store_ignores_corrupt_files_and_orders_by_update(tmp_path):
    store = ChatStore(tmp_path / "chats")
    a = ChatSession(id="aaa111")
    a.add("user", "первый")
    b = ChatSession(id="bbb222")
    b.add("user", "второй")
    time.sleep(0.01)
    b.updated_at = time.time() + 10
    store.save(a)
    store.save(b)
    (tmp_path / "chats" / "broken.json").write_text("{oops", encoding="utf-8")

    sessions = store.list_sessions()
    assert [item.id for item in sessions] == ["bbb222", "aaa111"]

    store.delete("aaa111")
    assert [item.id for item in store.list_sessions()] == ["bbb222"]


def test_message_openai_payload_omits_empty_fields():
    payload = ChatMessage(role="user", content="hi").to_openai()
    assert payload == {"role": "user", "content": "hi"}
