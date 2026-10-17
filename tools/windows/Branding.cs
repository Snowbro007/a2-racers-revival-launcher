using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

namespace A2Revival.Windows {
    internal static class Branding {
        internal static Bitmap Image(int size) {
            var image = new Bitmap(size, size);
            using (var g = Graphics.FromImage(image)) {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                float margin = size * .055f, radius = size * .12f;
                var rect = new RectangleF(margin, margin, size - 2 * margin, size - 2 * margin);
                using (var path = new GraphicsPath()) {
                    float d = radius * 2;
                    path.AddArc(rect.X, rect.Y, d, d, 180, 90);
                    path.AddArc(rect.Right - d, rect.Y, d, d, 270, 90);
                    path.AddArc(rect.Right - d, rect.Bottom - d, d, d, 0, 90);
                    path.AddArc(rect.X, rect.Bottom - d, d, d, 90, 90);
                    path.CloseFigure();
                    using (var red = new SolidBrush(Color.FromArgb(199, 10, 15))) g.FillPath(red, path);
                    using (var white = new Pen(Color.White, Math.Max(1, size * .025f))) g.DrawPath(white, path);
                }
                using (var font = new Font("Segoe UI", size * .43f, FontStyle.Bold, GraphicsUnit.Pixel))
                using (var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center })
                    g.DrawString("A2", font, Brushes.White, new RectangleF(0, -size * .015f, size, size), format);
            }
            return image;
        }
        internal static void WriteIcon(string path) {
            int[] sizes = {16, 24, 32, 48, 64, 128, 256};
            var images = new byte[sizes.Length][];
            for (int i = 0; i < sizes.Length; i++) {
                using (var bitmap = Image(sizes[i])) using (var stream = new MemoryStream()) {
                    bitmap.Save(stream, ImageFormat.Png); images[i] = stream.ToArray();
                }
            }
            using (var stream = new FileStream(path, FileMode.CreateNew)) using (var writer = new BinaryWriter(stream)) {
                writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
                int offset = 6 + 16 * sizes.Length;
                for (int i = 0; i < sizes.Length; i++) {
                    writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i])); writer.Write((byte)(sizes[i] == 256 ? 0 : sizes[i]));
                    writer.Write((byte)0); writer.Write((byte)0); writer.Write((ushort)1); writer.Write((ushort)32);
                    writer.Write(images[i].Length); writer.Write(offset); offset += images[i].Length;
                }
                foreach (var bytes in images) writer.Write(bytes);
            }
        }
    }
}
