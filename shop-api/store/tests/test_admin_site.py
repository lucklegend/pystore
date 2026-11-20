from django.test import TestCase

from store.tests.factories import make_order, make_product, make_user


class OrderChangelistTests(TestCase):
    def test_lists_each_orders_items_and_total(self):
        user = make_user(is_staff=True)
        user.is_superuser = True
        user.save()
        self.client.force_login(user)
        mug = make_product("Mug", price="8.00")
        tee = make_product("Tee", price="15.50")
        make_order(user, [(mug, 2), (tee, 1)])

        response = self.client.get("/admin/store/order/")

        self.assertContains(response, "2 × Mug<br>1 × Tee")
        self.assertContains(response, "31.50")


class AdminPerPageTests(TestCase):
    def setUp(self):
        user = make_user(is_staff=True)
        user.is_superuser = True
        user.save()
        self.client.force_login(user)
        for _ in range(25):
            make_product()

    def shown(self, query: dict) -> int:
        response = self.client.get("/admin/store/product/", query)
        self.assertEqual(response.status_code, 200)
        return len(response.context["cl"].result_list)

    def test_defaults_to_10(self):
        self.assertEqual(self.shown({}), 10)

    def test_uses_the_chosen_size_alongside_filters(self):
        self.assertEqual(self.shown({"per_page": "20", "is_active__exact": "1"}), 20)

    def test_falls_back_to_10_for_sizes_not_offered(self):
        for value in ("7", "abc", "1000"):
            with self.subTest(per_page=value):
                self.assertEqual(self.shown({"per_page": value}), 10)
