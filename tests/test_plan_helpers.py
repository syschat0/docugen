from app.services.llm import collect_leaf_titles, tree_skeleton

TREE = [
    {
        "id": "1",
        "title": "Intro",
        "purpose": "context",
        "children": [
            {"id": "1.1", "title": "Background", "key_points": ["a"], "children": []},
            {
                "id": "1.2",
                "title": "Scope",
                "children": [
                    {"id": "1.2.1", "title": "In scope", "children": []},
                ],
            },
        ],
    },
    {"id": "2", "title": "Body", "children": []},
]


class TestCollectLeafTitles:
    def test_collects_only_leaves(self):
        assert collect_leaf_titles(TREE) == ["Background", "In scope", "Body"]

    def test_ignores_non_dict_nodes(self):
        assert collect_leaf_titles(["junk", {"title": "Leaf"}]) == ["Leaf"]

    def test_empty(self):
        assert collect_leaf_titles([]) == []


class TestTreeSkeleton:
    def test_keeps_only_ids_and_titles(self):
        skeleton = tree_skeleton(TREE)
        assert skeleton[0] == {
            "id": "1",
            "title": "Intro",
            "children": [
                {"id": "1.1", "title": "Background"},
                {"id": "1.2", "title": "Scope", "children": [{"id": "1.2.1", "title": "In scope"}]},
            ],
        }
        assert skeleton[1] == {"id": "2", "title": "Body"}

    def test_much_smaller_than_full_tree(self):
        import json

        full = json.dumps(TREE, ensure_ascii=False)
        slim = json.dumps(tree_skeleton(TREE), ensure_ascii=False)
        assert len(slim) < len(full)
