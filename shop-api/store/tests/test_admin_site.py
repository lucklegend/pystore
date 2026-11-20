from django.contrib import admin
from django.test import RequestFactory, TestCase

from store.tests.factories import make_category, make_order, make_product, make_user


class AdminAppOrderTests(TestCase):
    def test_store_is_listed_before_the_built_in_apps(self):
        user = make_user(is_staff=True)
        user.is_superuser = True
        user.save()
        request = RequestFactory().get("/admin/")
        request.user = user

        labels = [app["app_label"] for app in admin.site.get_app_list(request)]

        self.assertEqual(labels[0], "store")
        self.assertIn("auth", labels[1:])
        self.assertIn("authtoken", labels[1:])


class AdminActionPromptTests(TestCase):
    def test_store_changelists_prompt_select_action(self):
        user = make_user(is_staff=True)
        user.is_superuser = True
        user.save()
        self.client.force_login(user)
        # The action bar only renders when the list has rows.
        product = make_product(category=make_category())
        make_order(user, [(product, 1)])

        for model in ("category", "product", "order"):
            with self.subTest(model=model):
                response = self.client.get(f"/admin/store/{model}/")
                self.assertContains(response, '<option value="" selected>Select action</option>', html=True)
                self.assertNotContains(response, "---------")


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
