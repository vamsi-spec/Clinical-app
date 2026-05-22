import cloudinary from "cloudinary";
import logger from "../utils/logger";


cloudinary.config({
    cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
    api_key: process.env.CLOUDINARY_API_KEY,
    api_secret: process.env.CLOUDINARY_API_SECRET,
    secure: true,
})


export const uploadAudio = async (filePath, options = {}) => {
    try {
        const result = await cloudinary.uploader.upload(filePath, {
            resource_type: "video",
            folder: 'clinical-notes/audio',
            ...options,

        })

        logger.info(`Audio uploaded to Cloudinary: ${result.public_id}`)
        return {
            url: result.secure_url,
            publicId: result.public_id,
            duration: result.duration,
            format: result.format,
            bytes: result.bytes,
        }
    } catch (error) {
        logger.error('Cloudinary upload failed:', error.message)
        throw new Error(`Audio upload failed: ${error.message}`)
    }
}


export const deleteAudio = async (publicId) => {
    try {
        const result = await cloudinary.uploader.destroy(publicId, {
            resource_type: 'video',
        })
        logger.info(`Audio deleted from cloudinary: ${publicId}`)
        return result
    } catch (error) {
        logger.error('Cloudinary delete failed:', error.message)
        throw new Error(`Audio delete failed: ${error.message}`)
    }
}