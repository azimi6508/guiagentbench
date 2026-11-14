import unittest

from gui_agent_bench.runners.codex_startup import admitted_layer


def layer(kind, config=None):
    return {'name': {'type': kind}, 'config': {} if config is None else config}


class ConfigLayerTests(unittest.TestCase):
    def test_benchmark_layer_types_are_admitted(self):
        for kind in ('system', 'user', 'sessionFlags', 'legacyManagedConfigFile'):
            with self.subTest(kind=kind):
                self.assertTrue(admitted_layer(layer(kind, {'model': 'x', 'features': {}})))

    def test_enterprise_layer_may_only_set_model(self):
        self.assertTrue(admitted_layer(layer('enterpriseManaged', {'model': 'admin-default'})))
        self.assertTrue(admitted_layer(layer('enterpriseManaged', {})))
        for extra in ('features', 'mcp_servers', 'instructions', 'model_reasoning_effort', 'web_search', 'tools'):
            with self.subTest(extra=extra):
                self.assertFalse(admitted_layer(layer('enterpriseManaged', {'model': 'x', extra: 'y'})))

    def test_enterprise_layer_requires_object_config(self):
        self.assertFalse(admitted_layer({'name': {'type': 'enterpriseManaged'}}))
        self.assertFalse(admitted_layer({'name': {'type': 'enterpriseManaged'}, 'config': ['model']}))

    def test_unknown_layer_types_are_rejected(self):
        for kind in ('project', 'mdm', 'cloud', None):
            with self.subTest(kind=kind):
                self.assertFalse(admitted_layer(layer(kind, {})))
        self.assertFalse(admitted_layer({'config': {}}))


if __name__ == '__main__':
    unittest.main()
