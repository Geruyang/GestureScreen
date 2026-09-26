param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot '../Build/agent-team/round4/executor'
}
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($outputPath) | Out-Null
$sourcePath = Join-Path $PSScriptRoot 'UsbHubReadOnly.cs'
$source = [IO.File]::ReadAllText($sourcePath)
# One assembly lets the offline test call internal decoders. Scan() is never invoked.
$testSource = @'
public static class UsbHubOfflineTests
{
    static int checks;
    static void Check(bool condition, string label)
    {
        checks++;
        if (!condition) throw new System.Exception("Offline check failed: " + label);
    }
    static void Put(byte[] b, int offset, uint value)
    { System.BitConverter.GetBytes(value).CopyTo(b, offset); }
    public static string Run()
    {
        Check(UsbHubReadOnly.GET_NODE_INFORMATION == 0x220408, "SDK node IOCTL");
        Check(UsbHubReadOnly.GET_ROOT_HUB_NAME == 0x220408, "SDK root IOCTL");
        Check(UsbHubReadOnly.GET_CONNECTION_EX == 0x220448, "SDK EX IOCTL");
        Check(UsbHubReadOnly.GET_ATTRIBUTES == 0x220440, "SDK attributes IOCTL");
        string reason, root; int status, ports; ushort vid, pid; uint attributes;
        byte[] ex = new byte[365]; Put(ex, 0, 4); Put(ex, 31, 4);
        ex[12] = 0xC9; ex[13] = 0x1F; ex[14] = 1; ex[15] = 0x56;
        for (uint len = 0; len < 35; len++)
        {
            Check(!UsbHubReadOnly.DecodeEx(ex, len, 4, out status, out vid, out pid, out reason)
                && status == -1 && vid == 0 && pid == 0, "EX short cannot report overcurrent " + len);
        }
        Check(UsbHubReadOnly.DecodeEx(ex, 35, 4, out status, out vid, out pid, out reason)
            && status == 4 && vid == 0x1FC9 && pid == 0x5601, "EX valid offsets");
        Put(ex, 31, 0);
        Check(!UsbHubReadOnly.DecodeEx(ex, 34, 4, out status, out vid, out pid, out reason)
            && status == -1, "EX short cannot report normal");
        Check(!UsbHubReadOnly.DecodeEx(ex, 366, 4, out status, out vid, out pid, out reason)
            && status == -1, "EX returned exceeds buffer");
        Check(!UsbHubReadOnly.DecodeEx(ex, 35, 3, out status, out vid, out pid, out reason)
            && status == -1 && reason == "connection_index_mismatch", "EX wrong port");
        byte[] attr = new byte[12]; Put(attr, 0, 4); Put(attr, 4, 4); Put(attr, 8, 0x1234);
        for (uint len = 0; len < 12; len++)
            Check(!UsbHubReadOnly.DecodeAttributes(attr, len, 4, out status, out attributes, out reason)
                && status == -1 && attributes == 0, "attributes short cannot report overcurrent " + len);
        Check(UsbHubReadOnly.DecodeAttributes(attr, 12, 4, out status, out attributes, out reason)
            && status == 4 && attributes == 0x1234, "attributes valid offsets");
        Put(attr, 4, 0);
        Check(!UsbHubReadOnly.DecodeAttributes(attr, 11, 4, out status, out attributes, out reason)
            && status == -1, "attributes short cannot report normal");
        Check(!UsbHubReadOnly.DecodeAttributes(attr, 13, 4, out status, out attributes, out reason),
            "attributes returned exceeds buffer");
        Check(!UsbHubReadOnly.DecodeAttributes(attr, 12, 3, out status, out attributes, out reason)
            && reason == "connection_index_mismatch", "attributes wrong port");
        byte[] node = new byte[76]; node[6] = 9;
        for (uint len = 0; len < 76; len++)
            Check(!UsbHubReadOnly.DecodeNode(node, len, out ports, out reason) && ports == -1,
                "node short cannot supply port count " + len);
        Check(UsbHubReadOnly.DecodeNode(node, 76, out ports, out reason) && ports == 9, "node valid port offset");
        node[6] = 0;
        Check(UsbHubReadOnly.DecodeNode(node, 76, out ports, out reason) && ports == 0, "node zero actual ports");
        node[6] = 255;
        Check(UsbHubReadOnly.DecodeNode(node, 76, out ports, out reason) && ports == 255, "node full byte port count");
        Check(!UsbHubReadOnly.DecodeNode(node, 77, out ports, out reason), "node returned exceeds buffer");
        Put(node, 0, 1);
        Check(!UsbHubReadOnly.DecodeNode(node, 76, out ports, out reason) && ports == -1, "node wrong type");
        byte[] name = new byte[20]; Put(name, 0, 12);
        System.Text.Encoding.Unicode.GetBytes("Hub\0").CopyTo(name, 4);
        for (uint len = 0; len < 6; len++)
            Check(!UsbHubReadOnly.DecodeRoot(name, len, out root, out reason), "root short " + len);
        Check(UsbHubReadOnly.DecodeRoot(name, 12, out root, out reason) && root == "Hub", "root valid name");
        Check(!UsbHubReadOnly.DecodeRoot(name, 10, out root, out reason), "root actual exceeds return");
        Check(!UsbHubReadOnly.DecodeRoot(name, 21, out root, out reason), "root return exceeds buffer");
        name[10] = 1;
        Check(!UsbHubReadOnly.DecodeRoot(name, 12, out root, out reason), "root missing terminator");
        Put(name, 0, 11);
        Check(!UsbHubReadOnly.DecodeRoot(name, 12, out root, out reason), "root odd UTF16 length");
        Check(!UsbHubReadOnly.LengthValid(null, 0, 1, out reason), "null buffer");
        return "passed=" + checks + ";failed=0;offline_only=true;scan_invoked=false;native_io_invoked=false";
    }
}
'@
Add-Type -TypeDefinition ($source + [Environment]::NewLine + $testSource) -Language CSharp
$result = [UsbHubOfflineTests]::Run()
$record = [ordered]@{
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    source = [IO.Path]::GetFullPath($sourcePath)
    sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    compiler = 'Windows PowerShell Add-Type CSharp'
    sdk = 'Windows Kits 10.0.26100.0 shared usbioctl.h, usbiodef.h, usb100.h -> usbspec.h'
    result = $result
    hardware_access = $false
}
[IO.File]::WriteAllText((Join-Path $outputPath 'offline-tests.json'), ($record | ConvertTo-Json))
[IO.File]::WriteAllText((Join-Path $outputPath 'offline-tests.txt'), $result + [Environment]::NewLine)
$result
