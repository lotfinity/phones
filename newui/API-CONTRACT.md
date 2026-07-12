# PriceBridge — API Contract

Backend: Django REST Framework
Base URL: `https://api.pricebridge.com/v1`

## Authentication

```
POST /auth/token/
```

**Request:**
```json
{
  "email": "ahmet@example.com",
  "password": "••••••••"
}
```

**Response:**
```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "usr_01H5...",
    "email": "ahmet@example.com",
    "businessName": "Istanbul Electronics",
    "role": "buyer"
  }
}
```

---

## Devices

### List Devices

```
GET /devices/
```

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `brand` | string | — | Filter by brand (Apple, Samsung, etc.) |
| `category` | string | — | Filter by category (iPhone, Samsung, Laptops, Consoles) |
| `min_profit` | int | 0 | Minimum expected profit in TRY |
| `max_cost` | int | 999999 | Maximum delivered cost in TRY |
| `trust_level` | string | — | Filter by trust (Verified, High, Standard) |
| `condition` | string | — | Filter by condition grade |
| `sort` | string | `profit` | Sort: profit, cost, newest, resale |
| `search` | string | — | Full-text search on model, brand |
| `page` | int | 1 | Page number |
| `page_size` | int | 20 | Results per page |

**Response:**
```json
{
  "count": 248,
  "next": "https://api.pricebridge.com/v1/devices/?page=2",
  "results": [
    {
      "id": "dev_01J5K3M...",
      "model": "iPhone 15 Pro Max",
      "brand": "Apple",
      "category": "iPhone",
      "storage": "256 GB",
      "color": "Natural Titanium",
      "condition": "Grade A",
      "batteryHealth": 91,
      "boxIncluded": true,
      "accessoriesIncluded": true,
      "images": ["https://cdn.pricebridge.com/devices/...jpg"],
      "deliveredCost": 47850,
      "currency": "TRY",
      "resaleRangeLow": 56000,
      "resaleRangeHigh": 60000,
      "expectedProfit": 9150,
      "profitPercent": 19.1,
      "listingAge": "2025-07-12T08:30:00Z",
      "trustLevel": "Verified",
      "source": "Instagram",
      "origin": "Algeria",
      "seller": {
        "name": "dz_tech_imports",
        "rating": 4.8,
        "totalDeals": 342
      },
      "availability": "In stock",
      "inPurchasePlan": false,
      "saved": false,
      "createdAt": "2025-07-12T06:30:00Z"
    }
  ]
}
```

### Get Device Detail

```
GET /devices/{id}/
```

**Response:** (includes additional fields)
```json
{
  "id": "dev_01J5K3M...",
  "model": "iPhone 15 Pro Max",
  "brand": "Apple",
  "category": "iPhone",
  "storage": "256 GB",
  "color": "Natural Titanium",
  "condition": "Grade A",
  "batteryHealth": 91,
  "boxIncluded": true,
  "accessoriesIncluded": true,
  "images": ["..."],
  "description": "iPhone 15 Pro Max in excellent condition...",
  "deliveredCost": 47850,
  "currency": "TRY",
  "costBreakdown": {
    "devicePurchase": 32500,
    "currencyConversion": 850,
    "travelAllocation": 4200,
    "transport": 3800,
    "riskAllowance": 2400,
    "serviceAndOrganization": 1600,
    "total": 47850
  },
  "resaleRangeLow": 56000,
  "resaleRangeHigh": 60000,
  "expectedProfit": 9150,
  "profitPercent": 19.1,
  "quickSalePrice": 55000,
  "estimatedSaleTime": "3-5 days",
  "riskLevel": "Low",
  "listingAge": "2025-07-12T08:30:00Z",
  "trustLevel": "Verified",
  "source": "Instagram",
  "origin": "Algeria",
  "seller": {
    "name": "dz_tech_imports",
    "rating": 4.8,
    "totalDeals": 342
  },
  "availability": "In stock",
  "inPurchasePlan": false,
  "saved": false,
  "simConfig": "Dual eSIM",
  "region": "EU/Global",
  "imeiStatus": "Clean",
  "faceId": true,
  "cameras": "All working",
  "trueTone": true,
  "screenCondition": "No scratches",
  "cosmeticGrade": "A",
  "listingUrl": "https://instagram.com/p/...",
  "createdAt": "2025-07-12T06:30:00Z",
  "updatedAt": "2025-07-12T08:30:00Z"
}
```

### Get Similar Devices

```
GET /devices/{id}/similar/
```

**Response:** Array of device summaries (same format as list items)

---

## Budget

### Get Budget

```
GET /budget/
```

**Response:**
```json
{
  "id": "bud_01H5...",
  "total": 500000,
  "currency": "TRY",
  "used": 181600,
  "remaining": 318400,
  "deviceCount": 4,
  "updatedAt": "2025-07-12T10:00:00Z"
}
```

### Update Budget

```
PATCH /budget/
```

**Request:**
```json
{
  "total": 600000
}
```

**Response:** Updated budget object

---

## Purchase Plan

### Get Plan

```
GET /plan/
```

**Response:**
```json
{
  "id": "plan_01H5...",
  "devices": [
    {
      "deviceId": "dev_01J5K3M...",
      "model": "iPhone 15 Pro Max",
      "storage": "256 GB",
      "condition": "Grade A",
      "deliveredCost": 47850,
      "expectedProfit": 9150,
      "quantity": 1,
      "addedAt": "2025-07-12T10:00:00Z"
    }
  ],
  "totalCost": 181600,
  "totalResale": 215000,
  "totalProfit": 33400,
  "deviceCount": 4,
  "budget": {
    "total": 500000,
    "used": 181600,
    "remaining": 318400
  }
}
```

### Add Device to Plan

```
POST /plan/items/
```

**Request:**
```json
{
  "deviceId": "dev_01J5K3M...",
  "quantity": 1
}
```

**Response:** Updated plan object

### Update Plan Item

```
PATCH /plan/items/{deviceId}/
```

**Request:**
```json
{
  "quantity": 2
}
```

### Remove Device from Plan

```
DELETE /plan/items/{deviceId}/
```

### Confirm Plan

```
POST /plan/confirm/
```

**Response:**
```json
{
  "orderId": "ord_01H5...",
  "status": "pending",
  "message": "Purchase plan confirmed. A team member will contact you within 24 hours."
}
```

### Export Plan Summary

```
GET /plan/export/
```

**Response:** PDF or CSV download

---

## Saved Devices

### List Saved

```
GET /saved/
```

**Response:** Array of device summaries

### Save Device

```
POST /saved/
```

**Request:**
```json
{
  "deviceId": "dev_01J5K3M..."
}
```

### Unsave Device

```
DELETE /saved/{deviceId}/
```

---

## Search

### Search Devices

```
GET /search/?q=iPhone+15
```

**Response:**
```json
{
  "results": [
    {
      "id": "dev_01J5K3M...",
      "model": "iPhone 15 Pro Max",
      "brand": "Apple",
      "deliveredCost": 47850,
      "expectedProfit": 9150,
      "condition": "Grade A",
      "images": ["..."]
    }
  ],
  "suggestions": ["iPhone 15 Pro", "iPhone 15", "iPhone 14 Pro"],
  "recentSearches": ["Samsung S24", "Steam Deck"]
}
```

### Get Recent Searches

```
GET /search/recent/
```

### Get Suggested Models

```
GET /search/suggestions/
```

---

## Budget Optimizer

### Generate Optimized Plan

```
POST /optimizer/generate/
```

**Request:**
```json
{
  "budget": 500000,
  "strategy": "balanced",
  "constraints": {
    "maxDevices": 10,
    "maxPerModel": 2,
    "minBattery": 80,
    "minCondition": "Grade B",
    "maxCost": 80000,
    "minProfit": 3000,
    "preferredBrands": ["Apple", "Samsung"]
  }
}
```

**Response:**
```json
{
  "strategy": "balanced",
  "devices": [
    {
      "deviceId": "dev_01J5K3M...",
      "model": "iPhone 15 Pro Max",
      "deliveredCost": 47850,
      "expectedProfit": 9150,
      "riskLevel": "Low"
    }
  ],
  "totalCost": 412000,
  "totalResale": 495000,
  "totalProfit": 83000,
  "remaining": 88000,
  "riskLevel": "Low",
  "explanation": "This basket balances profit potential with sale speed by selecting 7 high-trust devices across iPhone and Samsung categories."
}
```

---

## User Profile

### Get Profile

```
GET /auth/profile/
```

**Response:**
```json
{
  "id": "usr_01H5...",
  "email": "ahmet@example.com",
  "businessName": "Istanbul Electronics",
  "location": "Istanbul, Türkiye",
  "role": "buyer",
  "memberSince": "2025-01-15",
  "budget": {
    "total": 500000,
    "currency": "TRY"
  }
}
```

### Update Profile

```
PATCH /auth/profile/
```

---

## Notifications

### List Notifications

```
GET /notifications/
```

**Response:**
```json
{
  "results": [
    {
      "id": "ntf_01H5...",
      "type": "price_drop",
      "title": "Price drop on iPhone 15 Pro Max",
      "message": "Delivered cost dropped to 45,200 TRY",
      "deviceId": "dev_01J5K3M...",
      "read": false,
      "createdAt": "2025-07-12T14:00:00Z"
    }
  ]
}
```

### Mark as Read

```
PATCH /notifications/{id}/
```

**Request:**
```json
{
  "read": true
}
```

---

## Currency Rates

### Get Current Rates

```
GET /currency/rates/
```

**Response:**
```json
{
  "EUR_TRY": 35.42,
  "EUR_DZD": 142.30,
  "USD_TRY": 32.85,
  "updatedAt": "2025-07-12T12:00:00Z"
}
```

---

## Error Responses

All endpoints return:

```json
{
  "error": {
    "code": "not_found",
    "message": "Device not found"
  }
}
```

**Status codes:**
- `200` — Success
- `201` — Created
- `204` — No content (delete)
- `400` — Bad request
- `401` — Unauthorized
- `403` — Forbidden
- `404` — Not found
- `429` — Rate limited
- `500` — Server error

---

## Data Models

### Device
```
Device {
  id: UUID
  model: String
  brand: String
  category: String
  storage: String
  color: String
  condition: String (Grade A+, A, A-, B+, B)
  batteryHealth: Int?
  boxIncluded: Boolean
  accessoriesIncluded: Boolean
  images: [String]
  description: String
  deliveredCost: Int (TRY)
  costBreakdown: CostBreakdown
  resaleRangeLow: Int
  resaleRangeHigh: Int
  expectedProfit: Int
  profitPercent: Float
  quickSalePrice: Int
  estimatedSaleTime: String
  riskLevel: String (Low, Medium, High)
  trustLevel: String (Verified, High, Standard)
  source: String (Instagram, Ouedkniss)
  origin: String (Algeria)
  seller: Seller
  availability: String
  listingUrl: String
  simConfig: String?
  region: String?
  imeiStatus: String?
  faceId: Boolean?
  cameras: String?
  trueTone: Boolean?
  screenCondition: String?
  cosmeticGrade: String?
  createdAt: DateTime
  updatedAt: DateTime
}

CostBreakdown {
  devicePurchase: Int
  currencyConversion: Int
  travelAllocation: Int
  transport: Int
  riskAllowance: Int
  serviceAndOrganization: Int
  total: Int
}

Seller {
  name: String
  rating: Float
  totalDeals: Int
}
```

### Budget
```
Budget {
  id: UUID
  total: Int
  currency: String
  used: Int
  remaining: Int
  deviceCount: Int
  updatedAt: DateTime
}
```

### PlanItem
```
PlanItem {
  deviceId: UUID
  quantity: Int
  addedAt: DateTime
}
```

---

## Django Models Reference

```python
# devices/models.py
class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    model = models.CharField(max_length=200)
    brand = models.CharField(max_length=100)
    category = models.CharField(max_length=50)
    storage = models.CharField(max_length=50)
    color = models.CharField(max_length=100)
    condition = models.CharField(max_length=20)
    battery_health = models.IntegerField(null=True, blank=True)
    box_included = models.BooleanField(default=False)
    accessories_included = models.BooleanField(default=False)
    description = models.TextField()
    delivered_cost = models.IntegerField()
    resale_range_low = models.IntegerField()
    resale_range_high = models.IntegerField()
    expected_profit = models.IntegerField()
    quick_sale_price = models.IntegerField()
    estimated_sale_time = models.CharField(max_length=50)
    risk_level = models.CharField(max_length=20)
    trust_level = models.CharField(max_length=20)
    source = models.CharField(max_length=50)
    origin = models.CharField(max_length=50)
    listing_url = models.URLField()
    sim_config = models.CharField(max_length=50, null=True)
    region = models.CharField(max_length=50, null=True)
    imei_status = models.CharField(max_length=20, null=True)
    face_id = models.BooleanField(null=True)
    cameras = models.CharField(max_length=50, null=True)
    true_tone = models.BooleanField(null=True)
    screen_condition = models.CharField(max_length=100, null=True)
    cosmetic_grade = models.CharField(max_length=10, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DeviceImage(models.Model):
    device = models.ForeignKey(Device, related_name='images', on_delete=models.CASCADE)
    url = models.URLField()
    order = models.IntegerField(default=0)


class CostBreakdown(models.Model):
    device = models.OneToOneField(Device, related_name='cost_breakdown', on_delete=models.CASCADE)
    device_purchase = models.IntegerField()
    currency_conversion = models.IntegerField()
    travel_allocation = models.IntegerField()
    transport = models.IntegerField()
    risk_allowance = models.IntegerField()
    service_and_organization = models.IntegerField()


class Seller(models.Model):
    name = models.CharField(max_length=200)
    rating = models.FloatField()
    total_deals = models.IntegerField()
    devices = models.ManyToManyField(Device, related_name='sellers')


class Budget(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    total = models.IntegerField(default=500000)
    currency = models.CharField(max_length=3, default='TRY')


class PlanItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)


class SavedDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'device')
```

---

## Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/token/` | Login, get tokens |
| GET | `/auth/profile/` | Get user profile |
| PATCH | `/auth/profile/` | Update profile |
| GET | `/devices/` | List devices with filters |
| GET | `/devices/{id}/` | Get device detail |
| GET | `/devices/{id}/similar/` | Get similar devices |
| GET | `/budget/` | Get budget |
| PATCH | `/budget/` | Update budget |
| GET | `/plan/` | Get purchase plan |
| POST | `/plan/items/` | Add device to plan |
| PATCH | `/plan/items/{id}/` | Update plan item |
| DELETE | `/plan/items/{id}/` | Remove from plan |
| POST | `/plan/confirm/` | Confirm purchase plan |
| GET | `/plan/export/` | Export plan summary |
| GET | `/saved/` | List saved devices |
| POST | `/saved/` | Save device |
| DELETE | `/saved/{id}/` | Unsave device |
| GET | `/search/` | Search devices |
| GET | `/search/recent/` | Recent searches |
| GET | `/search/suggestions/` | Suggested models |
| POST | `/optimizer/generate/` | Generate optimized plan |
| GET | `/notifications/` | List notifications |
| PATCH | `{id}/` | Mark notification read |
| GET | `/currency/rates/` | Get currency rates |
