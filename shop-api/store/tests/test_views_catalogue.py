from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from store.models import Category, Product
from store.views import parse_id_list

from .factories import make_category, make_order, make_product, make_user

PRODUCTS = "/api/products/"
CATEGORIES = "/api/categories/"


def product_url(product: Product) -> str:
    return f"{PRODUCTS}{product.pk}/"


def names(response) -> list[str]:
    return [product["name"] for product in response.data["results"]]


class ParseIdListTests(SimpleTestCase):
    def test_keeps_digit_parts_and_drops_the_rest(self):
        self.assertEqual(parse_id_list("1,2, 3 ,x,-4,,5.0,6"), [1, 2, 3, 6])

    def test_empty_string_gives_no_ids(self):
        self.assertEqual(parse_id_list(""), [])


class CategoryApiTests(APITestCase):
    def test_list_is_unpaginated_and_sorted_by_name(self):
        make_category("Tea")
        make_category("Coffee")

        response = self.client.get(CATEGORIES)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([category["name"] for category in response.data], ["Coffee", "Tea"])

    def test_staff_can_create(self):
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.client.post(CATEGORIES, {"name": "Snacks"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Category.objects.filter(name="Snacks").exists())

    def test_customers_and_anonymous_users_cannot_create(self):
        response = self.client.post(CATEGORIES, {"name": "Snacks"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(make_user())
        response = self.client.post(CATEGORIES, {"name": "Snacks"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertFalse(Category.objects.exists())


class ProductListTests(APITestCase):
    def test_customers_see_only_active_products(self):
        make_product("Shown")
        make_product("Hidden", is_active=False)

        response = self.client.get(PRODUCTS)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(names(response), ["Shown"])
        self.assertEqual(response.data["count"], 1)

    def test_staff_see_inactive_products_too(self):
        make_product("Shown")
        make_product("Hidden", is_active=False)
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.client.get(PRODUCTS)

        self.assertCountEqual(names(response), ["Shown", "Hidden"])

    def test_includes_category_name(self):
        make_product("Sencha", category=make_category("Tea"))
        make_product("Loose")

        response = self.client.get(PRODUCTS)

        by_name = {product["name"]: product for product in response.data["results"]}
        self.assertEqual(by_name["Sencha"]["category_name"], "Tea")
        self.assertIsNone(by_name["Loose"]["category_name"])

    def test_filters_by_category(self):
        tea = make_category("Tea")
        make_product("Sencha", category=tea)
        make_product("Espresso", category=make_category("Coffee"))

        response = self.client.get(PRODUCTS, {"category": tea.pk})

        self.assertEqual(names(response), ["Sencha"])

    def test_ignores_a_non_numeric_category(self):
        make_product("Sencha", category=make_category("Tea"))
        make_product("Loose")

        response = self.client.get(PRODUCTS, {"category": "tea"})

        self.assertEqual(response.data["count"], 2)

    def test_filters_by_ids(self):
        first = make_product("First")
        make_product("Second")
        third = make_product("Third")

        response = self.client.get(PRODUCTS, {"ids": f"{first.pk},{third.pk},junk"})

        self.assertCountEqual(names(response), ["First", "Third"])

    def test_empty_ids_matches_nothing(self):
        make_product()

        response = self.client.get(PRODUCTS, {"ids": ""})

        self.assertEqual(response.data["count"], 0)

    def test_searches_name_and_description(self):
        make_product("Green tea")
        make_product("Mug", description="Fits a big tea bag")
        make_product("Spoon")

        response = self.client.get(PRODUCTS, {"search": "tea"})

        self.assertCountEqual(names(response), ["Green tea", "Mug"])

    def test_orders_by_price(self):
        make_product("Mid", price="5.00")
        make_product("Cheap", price="1.00")
        make_product("Dear", price="9.00")

        ascending = self.client.get(PRODUCTS, {"ordering": "price"})
        descending = self.client.get(PRODUCTS, {"ordering": "-price"})

        self.assertEqual(names(ascending), ["Cheap", "Mid", "Dear"])
        self.assertEqual(names(descending), ["Dear", "Mid", "Cheap"])

    def test_paginates_with_page_size_capped_at_100(self):
        Product.objects.bulk_create(Product(name=f"P{index}", price="1.00") for index in range(105))

        default = self.client.get(PRODUCTS)
        custom = self.client.get(PRODUCTS, {"page_size": 5})
        capped = self.client.get(PRODUCTS, {"page_size": 500})

        self.assertEqual(len(default.data["results"]), 12)
        self.assertEqual(len(custom.data["results"]), 5)
        self.assertEqual(len(capped.data["results"]), 100)
        self.assertEqual(default.data["count"], 105)
        self.assertIsNotNone(default.data["next"])
        self.assertIsNone(default.data["previous"])


class ProductDetailTests(APITestCase):
    def test_customers_get_404_for_inactive_product(self):
        hidden = make_product(is_active=False)

        response = self.client.get(product_url(hidden))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_read_inactive_product(self):
        hidden = make_product(is_active=False)
        self.client.force_authenticate(make_user(is_staff=True))

        response = self.client.get(product_url(hidden))

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ProductWriteTests(APITestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True)

    def payload(self, **overrides) -> dict:
        return {"name": "Kettle", "price": "30.00", "stock": 4, **overrides}

    def test_staff_can_create_update_and_delete(self):
        self.client.force_authenticate(self.staff)

        created = self.client.post(PRODUCTS, self.payload(), format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        url = f"{PRODUCTS}{created.data['id']}/"

        updated = self.client.patch(url, {"price": "25.00"}, format="json")
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["price"], "25.00")

        deleted = self.client.delete(url)
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.exists())

    def test_rejects_negative_price(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(PRODUCTS, self.payload(price="-1.00"), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("price", response.data)

    def test_customers_cannot_write(self):
        product = make_product()
        self.client.force_authenticate(make_user())

        responses = [
            self.client.post(PRODUCTS, self.payload(), format="json"),
            self.client.patch(product_url(product), {"price": "0.01"}, format="json"),
            self.client.delete(product_url(product)),
        ]

        self.assertEqual([response.status_code for response in responses], [status.HTTP_403_FORBIDDEN] * 3)
        product.refresh_from_db()
        self.assertEqual(str(product.price), "10.00")

    def test_deleting_an_ordered_product_returns_409(self):
        product = make_product()
        make_order(make_user(), [(product, 1)])
        self.client.force_authenticate(self.staff)

        response = self.client.delete(product_url(product))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Mark it inactive", response.data["detail"])
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
