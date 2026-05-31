# Image Format Conversion & Upload Error Handling Update

The system upload process must be improved to properly handle different image formats uploaded by users.

Currently, images taken with devices such as iPhones may fail because of unsupported formats (such as HEIC/HEIF).

This creates a poor user experience and interrupts the body measurement workflow.

The upload system should be updated with the following behavior.

---

# Automatic Image Format Conversion

If the uploaded image format is not supported by the AI processing pipeline, the system should automatically:

* Detect the image format
* Convert the image into a supported format
* Continue processing without interrupting the user

Recommended supported processing formats:

* JPG / JPEG
* PNG

Recommended conversion behavior:

* HEIC → JPG
* HEIF → JPG
* WEBP → JPG (if necessary)

The conversion process should happen automatically in backend or upload preprocessing logic.

The user should not need to manually convert images.

---

# iPhone Compatibility

The system must fully support images captured from:

* iPhone devices
* HEIC/HEIF camera outputs
* Modern mobile image formats

If the uploaded image is valid but unsupported internally, the system should convert it automatically instead of rejecting it.

---

# Upload Validation Requirements

The upload system should validate:

* File format
* Corrupted images
* Empty files
* Unsupported image types
* Extremely low resolution images
* Incomplete uploads

before AI processing starts.

---

# User-Friendly Persian Error Messages

If a problem occurs during upload or preprocessing, the system should display clear Persian error messages to the user.

Error messages must:

* Be understandable for non-technical users
* Clearly explain the problem
* Suggest how to fix it if possible

---

# Example Persian Error Messages

## Unsupported Format

```text id="c0j50o"
فرمت تصویر پشتیبانی نمی‌شود. لطفاً تصویر دیگری انتخاب کنید.
```

---

## Corrupted Image

```text id="r9l5x7"
فایل تصویر خراب است و قابل پردازش نیست. لطفاً دوباره تلاش کنید.
```

---

## Upload Failure

```text id="5p8c9v"
آپلود تصویر با مشکل مواجه شد. لطفاً اتصال اینترنت خود را بررسی کرده و دوباره تلاش کنید.
```

---

## Low Quality Image

```text id="tt8v4m"
کیفیت تصویر بسیار پایین است. لطفاً عکس واضح‌تری ثبت کنید.
```

---

## Incomplete Body Detection

```text id="x2a7cn"
بدن به‌صورت کامل داخل تصویر مشخص نیست. لطفاً دوباره عکس بگیرید.
```

---

## Poor Lighting

```text id="9kq1fp"
نور محیط مناسب نیست. لطفاً در محیط روشن‌تر عکس بگیرید.
```

---

# UX Requirements

The upload flow should:

* Continue automatically whenever possible
* Avoid technical error messages
* Hide internal conversion logic from users
* Minimize upload interruptions
* Keep the process simple and smooth

---

# Final Objective

The updated upload system should:

* Fully support modern mobile image formats
* Prevent unnecessary upload failures
* Improve iPhone compatibility
* Automatically convert unsupported image formats
* Provide clear Persian feedback to users
* Improve overall upload success rate and UX
