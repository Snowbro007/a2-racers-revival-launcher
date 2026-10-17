"""Pure MSZIP decoder for synthetic tests. No installer execution."""
import struct,zlib

def read_cab(data):
    if data[:4]!=b'MSCF' or len(data)<36:raise ValueError('Not a CAB.')
    size=struct.unpack_from('<I',data,8)[0];offset=struct.unpack_from('<I',data,16)[0]
    folders,count,flags=struct.unpack_from('<HHH',data,26)
    if size!=len(data) or flags or data[24:26]!=bytes((3,1)):raise ValueError('Unsupported/spanned CAB.')
    if not 36+8*folders<=offset<len(data):raise ValueError('Invalid CAB table bounds.')
    folder_data=[]
    for i in range(folders):
        position,blocks,compression=struct.unpack_from('<IHH',data,36+8*i)
        if compression!=1:raise ValueError('Expected ordinary MSZIP.')
        output=bytearray()
        for _ in range(blocks):
            if position+8>len(data):raise ValueError('Truncated CAB data.')
            checksum,compressed,expanded=struct.unpack_from('<IHH',data,position);position+=8
            block=data[position:position+compressed];position+=compressed
            if len(block)!=compressed or block[:2]!=b'CK' or expanded>32768:raise ValueError('Invalid MSZIP block.')
            decoder=zlib.decompressobj(-15,zdict=bytes(output[-32768:]))
            result=decoder.decompress(block[2:])+decoder.flush()
            if len(result)!=expanded or not decoder.eof or decoder.unused_data:raise ValueError('MSZIP size mismatch.')
            output.extend(result)
        folder_data.append(bytes(output))
    members={}
    for _ in range(count):
        if offset+16>len(data):raise ValueError('Truncated CAB file table.')
        length,start,folder,date,time,attrs=struct.unpack_from('<IIHHHH',data,offset);offset+=16
        end=data.find(b'\0',offset)
        if end<0:raise ValueError('Missing CAB filename terminator.')
        name=data[offset:end].decode('ascii');offset=end+1
        if name in members or folder>=len(folder_data) or start+length>len(folder_data[folder]):raise ValueError('Invalid CAB member.')
        members[name]=folder_data[folder][start:start+length]
    return members
