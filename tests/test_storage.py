from vera.storage import Store


def test_new_user_id_slugifies_and_dedupes(tmp_path):
    store = Store(tmp_path / "vera.json")
    assert store.new_user_id("Tom") == "tom"
    u = store.get_user("tom")
    u["name"] = "Tom"
    store.save_user(u)
    assert store.new_user_id("Tom") == "tom-2"


def test_new_user_id_handles_punctuation(tmp_path):
    store = Store(tmp_path / "vera.json")
    assert store.new_user_id("Mary O'Brien!") == "mary-o-brien"


def test_list_users_returns_everyone(tmp_path):
    store = Store(tmp_path / "vera.json")
    for uid, name in [("rose", "Rose"), ("tom", "Tom")]:
        u = store.get_user(uid)
        u["name"] = name
        store.save_user(u)
    names = {p["name"] for p in store.list_users()}
    assert names == {"Rose", "Tom"}
