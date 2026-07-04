# Data Model

`Category`, `Brand`, `ProductModel`, and `DeviceVariant` describe electronics generically. Phones are the first target, but the same model supports laptops, tablets, watches, and other devices.

`Source` identifies where data came from: Instagram, supplier lists, Sahibinden, or manual entry.

`InstagramPost` stores collected public post metadata, captions, and local media paths. `OCRResult` stores extracted image text and review fields.

`SupplierPrice` stores raw supplier rows plus parsed model, variant, USD price, optional EUR price, confidence, and active state.

`MarketListing` is the generic observed market listing table. It stores Algeria Instagram listings now and future Sahibinden listings later.

`CurrencyRate` is available for manually recording observed FX rates.

`OpportunitySnapshot` records point-in-time analysis using Algeria prices, supplier prices, optional future Sahibinden averages, simple margins, confidence, and recommendation.
