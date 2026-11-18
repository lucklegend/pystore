from decimal import Decimal

from django.core.management.base import BaseCommand

from store.models import Category, Product

DEMO_PRODUCTS = {
    "Apparel": [
        ("Classic Cotton Tee", "Soft, breathable everyday t-shirt.", "19.99", 40),
        ("Denim Jacket", "Timeless mid-wash denim jacket.", "79.00", 12),
        ("Wool Beanie", "Warm ribbed beanie for cold days.", "24.50", 30),
    ],
    "Home": [
        ("Ceramic Mug", "350 ml stoneware mug, dishwasher safe.", "14.00", 60),
        ("Linen Throw Pillow", "45×45 cm cover with insert.", "32.00", 20),
    ],
    "Electronics": [
        ("Wireless Earbuds", "Bluetooth 5.3 with charging case.", "59.99", 25),
        ("USB-C Charger 65W", "Compact GaN charger for laptop and phone.", "39.00", 35),
        ("Mechanical Keyboard", "Tenkeyless, hot-swappable switches.", "109.00", 8),
    ],
}


class Command(BaseCommand):
    help = "Create demo categories and products. Safe to run more than once."

    def handle(self, *args, **options) -> None:
        created = 0
        for category_name, products in DEMO_PRODUCTS.items():
            category, _ = Category.objects.get_or_create(name=category_name)
            for name, description, price, stock in products:
                _, was_created = Product.objects.get_or_create(
                    name=name,
                    defaults={
                        "category": category,
                        "description": description,
                        "price": Decimal(price),
                        "stock": stock,
                    },
                )
                created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Seeded store: {created} new products."))
