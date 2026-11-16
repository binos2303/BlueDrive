# Poppins tự host

Giữ Poppins normal ở đúng bốn weight 400, 500, 600, 700 đang dùng trong BlueDrive. `frontend/app/layout.tsx` nạp qua `next/font/local`, giữ `--font-poppins`, `display: swap` và design tokens. Không cần tải font qua mạng khi build hoặc thêm dependency runtime.

Nguồn: [Google Fonts, commit 8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5](https://github.com/google/fonts/tree/8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5/ofl/poppins), ngày nhập 16/11/2026. Các file TTF nguyên gốc, không chuyển đổi hoặc chỉnh glyph; giấy phép [OFL.txt](OFL.txt) đi cùng font. Full font giữ glyph ngoài Latin; bốn file tổng cộng 632.200 bytes, cần tính cả font khi đo asset payload.

| File / weight | SHA-256 |
| --- | --- |
| Poppins-Regular.ttf / 400 | `7e65201e9b79159e2300267cc885e16c8dcef2424cdfa09a29bfb0980a94a7ba` |
| Poppins-Medium.ttf / 500 | `90373e7d838d32468438fc3e152dca0bdb12edcab99ea639f158790b1ba1fd05` |
| Poppins-SemiBold.ttf / 600 | `d3bf1bdaf0550e83da9ac0b1d1d9fe6db086835a83aa28578e609a394b9a0286` |
| Poppins-Bold.ttf / 700 | `983676516167748b74de6f4771fb384c664fd913acb8b471122ecacf5da5ea6c` |
| OFL.txt (nguyên văn upstream) | `6be04893d770899a015649c7aa3b582f871b272f8747a92b78b17c3e5c8b2573` |

Không lấy lại từ nhánh `main` trong mỗi lần build. Khi cần cập nhật font, review version, license, glyph/metrics và checksum cùng nhiệm vụ; không đổi nhận diện để chữa lỗi kết nối Google Fonts.
