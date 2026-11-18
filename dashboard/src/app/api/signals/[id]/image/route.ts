import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'
import { imageResponseHeaders } from '@/lib/safeImage'

function detectContentType(buf: Buffer): string {
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg'
  if (buf.length >= 4 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return 'image/png'
  if (buf.length >= 4 && buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46) return 'image/gif'
  return 'image/jpeg'
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { id } = await params

    const signal = await prisma.signal.findUnique({
      where: { id },
      select: { imageData: true },
    })

    if (!signal || !signal.imageData) {
      return new NextResponse('No image', { status: 404 })
    }

    const imageBuffer = Buffer.from(signal.imageData, 'base64')

    // Guard against corrupted/truncated imageData (e.g. stored as raw bytes instead of base64)
    if (imageBuffer.length < 100) {
      return new NextResponse('No image', { status: 404 })
    }

    return new NextResponse(imageBuffer, {
      status: 200,
      headers: imageResponseHeaders(detectContentType(imageBuffer), 86400),
    })
  } catch (error) {
    console.error('Error serving signal image:', error)
    return new NextResponse('Internal Server Error', { status: 500 })
  }
}
