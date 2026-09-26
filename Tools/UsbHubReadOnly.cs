using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

// Windows SDK 10.0.26100.0 shared/usbioctl.h (pack 1), usb100.h -> usbspec.h.
// This helper issues only the four listed GET requests. It does not recover ports.
public static class UsbHubReadOnly
{
    const uint GENERIC_READ = 0x80000000, FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2;
    const uint OPEN_EXISTING = 3, FILE_ATTRIBUTE_NORMAL = 0x80;
    // Both functions are 258, but ROOT_HUB_NAME targets HCD and NODE_INFORMATION targets hub.
    internal const uint GET_ROOT_HUB_NAME = 0x220408, GET_NODE_INFORMATION = 0x220408;
    internal const uint GET_CONNECTION_EX = 0x220448, GET_ATTRIBUTES = 0x220440;
    internal const int NodeSize = 76, ExSize = 35, AttributesSize = 12;
    const int NameSize = 1024, ExBufferSize = ExSize + 30 * 11;
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateFile(string n, uint a, uint s, IntPtr sa, uint c, uint f, IntPtr t);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool DeviceIoControl(IntPtr h, uint code, [In] byte[] input, uint inLen,
        [Out] byte[] output, uint outLen, out uint ret, IntPtr ov);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr h);

    static IntPtr Open(string name) { return CreateFile(name, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero); }
    static bool Good(IntPtr h) { return h != IntPtr.Zero && h != new IntPtr(-1); }
    internal static bool LengthValid(byte[] b, uint returned, int needed, out string reason)
    {
        reason = b == null || returned > b.Length ? "invalid_returned_length" :
            returned < needed ? "short_return" : null;
        return reason == null;
    }
    internal static bool DecodeRoot(byte[] b, uint returned, out string root, out string reason)
    {
        root = null;
        if (!LengthValid(b, returned, 6, out reason)) return false;
        uint actual = BitConverter.ToUInt32(b, 0);
        if (actual < 6 || actual > returned || (actual - 4) % 2 != 0)
        { reason = "invalid_actual_length"; return false; }
        int end = -1;
        for (int i = 4; i + 1 < actual; i += 2)
            if (b[i] == 0 && b[i + 1] == 0) { end = i; break; }
        if (end < 0) { reason = "missing_name_terminator"; return false; }
        root = Encoding.Unicode.GetString(b, 4, end - 4);
        if (string.IsNullOrWhiteSpace(root)) { reason = "empty_name"; return false; }
        return true;
    }
    internal static bool DecodeNode(byte[] b, uint returned, out int ports, out string reason)
    {
        ports = -1;
        if (!LengthValid(b, returned, NodeSize, out reason)) return false;
        if (BitConverter.ToUInt32(b, 0) != 0) { reason = "unexpected_node_type"; return false; }
        ports = b[6]; // NodeType 4 + descriptor bNumberOfPorts offset 2.
        return true;
    }
    internal static bool DecodeEx(byte[] b, uint returned, uint requested, out int status,
        out ushort vid, out ushort pid, out string reason)
    {
        status = -1; vid = pid = 0;
        if (!LengthValid(b, returned, ExSize, out reason)) return false;
        if (BitConverter.ToUInt32(b, 0) != requested) { reason = "connection_index_mismatch"; return false; }
        status = BitConverter.ToInt32(b, 31);
        vid = BitConverter.ToUInt16(b, 12); pid = BitConverter.ToUInt16(b, 14);
        return true; // Only the fixed prefix is decoded, never the variable PipeList.
    }
    internal static bool DecodeAttributes(byte[] b, uint returned, uint requested,
        out int status, out uint attributes, out string reason)
    {
        status = -1; attributes = 0;
        if (!LengthValid(b, returned, AttributesSize, out reason)) return false;
        if (BitConverter.ToUInt32(b, 0) != requested) { reason = "connection_index_mismatch"; return false; }
        status = BitConverter.ToInt32(b, 4); attributes = BitConverter.ToUInt32(b, 8);
        return true;
    }
    static bool Query(IntPtr h, uint ioctl, byte[] input, byte[] output, out uint returned, out int error)
    {
        bool ok = DeviceIoControl(h, ioctl, input, (uint)input.Length, output,
            (uint)output.Length, out returned, IntPtr.Zero);
        error = ok ? 0 : Marshal.GetLastWin32Error();
        return ok;
    }
    static string Hex(byte[] b, uint returned)
    { return BitConverter.ToString(b, 0, (int)Math.Min(returned, (uint)b.Length)).Replace("-", ""); }
    static string Result(bool ok, bool decoded, string reason, int error)
    { return !ok ? "failed;win32=" + error : decoded ? "ok" : "invalid;reason=" + reason; }
    static string Index(byte[] b, uint returned)
    { return returned >= 4 && returned <= b.Length ? BitConverter.ToUInt32(b, 0).ToString() : "unavailable"; }

    public static string Scan() { return Scan(32, 32); }
    public static string Scan(int hcdLimit, int fallbackPortLimit)
    {
        if (hcdLimit < 1 || hcdLimit > 32 || fallbackPortLimit < 1 || fallbackPortLimit > 32)
            throw new ArgumentOutOfRangeException("Scan bounds must be 1..32.");
        if (!BitConverter.IsLittleEndian) throw new PlatformNotSupportedException("Windows little endian required.");
        var lines = new List<string>();
        lines.Add("read_only=true;timestamp_utc=" + DateTime.UtcNow.ToString("o") +
            ";hcd_limit=" + hcdLimit + ";fallback_port_limit=" + fallbackPortLimit + ";samples_per_query=1");
        lines.Add("ioctls=GET_ROOT_HUB_NAME:0x220408,GET_NODE_INFORMATION:0x220408," +
            "GET_NODE_CONNECTION_INFORMATION_EX:0x220448,GET_NODE_CONNECTION_ATTRIBUTES:0x220440");
        lines.Add("node_size=76;ex_fixed_size=35;ex_buffer_size=" + ExBufferSize +
            ";attributes_size=12;name_buffer_size=1024;pipe_list_decoded=false");
        for (int hcd = 0; hcd < hcdLimit; hcd++)
        {
            IntPtr controller = Open("\\\\.\\HCD" + hcd);
            if (!Good(controller)) { lines.Add("hcd=" + hcd + ";open=failed;win32=" + Marshal.GetLastWin32Error()); continue; }
            string root = null, reason = null; uint returned; int error; bool ok, decoded;
            try
            {
                byte[] input = new byte[NameSize], output = new byte[NameSize];
                ok = Query(controller, GET_ROOT_HUB_NAME, input, output, out returned, out error);
                decoded = ok && DecodeRoot(output, returned, out root, out reason);
                lines.Add("hcd=" + hcd + ";root_name_query=" + Result(ok, decoded, reason, error) +
                    ";bytes_returned=" + returned + ";raw_hex=" + Hex(output, returned) + ";root=" + root);
            }
            finally { CloseHandle(controller); }
            if (root == null || !decoded) continue;
            IntPtr hub = Open("\\\\.\\" + root);
            if (!Good(hub)) { lines.Add("hub=" + root + ";open=failed;win32=" + Marshal.GetLastWin32Error()); continue; }
            try
            {
                byte[] input = new byte[NodeSize], output = new byte[NodeSize];
                int ports = -1; reason = null;
                ok = Query(hub, GET_NODE_INFORMATION, input, output, out returned, out error);
                decoded = ok && DecodeNode(output, returned, out ports, out reason);
                bool knownCount = decoded;
                lines.Add("hub=" + root + ";node_info=" + Result(ok, decoded, reason, error) +
                    ";bytes_returned=" + returned + ";raw_hex=" + Hex(output, returned) +
                    ";ports=" + ports + ";port_count_source=" + (knownCount ? "node_info" : "bounded_fallback") +
                    ";scan_ports=" + (knownCount ? ports : fallbackPortLimit));
                for (uint p = 1; p <= (knownCount ? ports : fallbackPortLimit); p++)
                {
                    byte[] exInput = new byte[ExBufferSize], ex = new byte[ExBufferSize];
                    BitConverter.GetBytes(p).CopyTo(exInput, 0);
                    uint exReturned; int exError, status = -1; ushort vid = 0, pid = 0; reason = null;
                    bool exOk = Query(hub, GET_CONNECTION_EX, exInput, ex, out exReturned, out exError);
                    bool exDecoded = exOk && DecodeEx(ex, exReturned, p, out status, out vid, out pid, out reason);
                    string exResult = Result(exOk, exDecoded, reason, exError);
                    byte[] attrInput = new byte[AttributesSize], attr = new byte[AttributesSize];
                    BitConverter.GetBytes(p).CopyTo(attrInput, 0);
                    uint attrReturned, attributes = 0; int attrError, attrStatus = -1; reason = null;
                    bool attrOk = Query(hub, GET_ATTRIBUTES, attrInput, attr, out attrReturned, out attrError);
                    bool attrDecoded = attrOk && DecodeAttributes(attr, attrReturned, p, out attrStatus, out attributes, out reason);
                    string interpretation = exDecoded || attrDecoded ? "hub_reported_status" :
                        knownCount ? "query_failure_not_port_fault" : "possible_out_of_range_or_query_failure";
                    lines.Add("hub=" + root + ";port=" + p + ";port_range=" + (knownCount ? "verified" : "unverified_fallback") +
                        ";ex_query=" + exResult + ";ex_bytes_returned=" + exReturned + ";ex_connection_index=" + Index(ex, exReturned) +
                        ";status=" + status + ";vid=0x" + vid.ToString("X4") + ";pid=0x" + pid.ToString("X4") +
                        ";ex_raw_hex=" + Hex(ex, exReturned) + ";attr_query=" + Result(attrOk, attrDecoded, reason, attrError) +
                        ";attr_bytes_returned=" + attrReturned + ";attr_connection_index=" + Index(attr, attrReturned) +
                        ";attr_status=" + attrStatus + ";port_attributes=0x" + attributes.ToString("X8") +
                        ";attr_raw_hex=" + Hex(attr, attrReturned) + ";interpretation=" + interpretation);
                }
            }
            finally { CloseHandle(hub); }
        }
        return string.Join(Environment.NewLine, lines);
    }
}
