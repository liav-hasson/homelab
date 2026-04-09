// =============================================================================
// MongoDB Initialization Script for Kubernetes
// =============================================================================
// This script runs as a Kubernetes Job to initialize MongoDB with quiz data
// It is idempotent - safe to run multiple times (checks if data exists first)
//
// Usage: mongosh quizdb /scripts/init-mongodb.js
// =============================================================================

// Switch to the quiz database
db = db.getSiblingDB('quizdb');

print('=== Quiz Database Initialization Job ===');
print('Checking database state...');

// Check if data already exists
const existingCount = db.quiz_data.countDocuments();

if (existingCount > 0) {
    print(`Found ${existingCount} existing documents in database`);
    print('Recreating database from db.json to sync latest changes...');
    print('Deleting existing data...');
    const deleteResult = db.quiz_data.deleteMany({});
    print(`✓ Deleted ${deleteResult.deletedCount} documents`);
} else {
    print('Database is empty. Starting initialization...');
}

// Load the JSON data file
const fs = require('fs');
let data;

try {
    const rawData = fs.readFileSync('/init-data/db.json', 'utf8');
    data = JSON.parse(rawData);
    print('✓ Loaded quiz data from db.json');
} catch (e) {
    print('ERROR: Could not load db.json: ' + e.message);
    quit(1);
}

// Transform the JSON structure into MongoDB documents
// Input: { "Category": { "Subject": { "keywords": [...], "style_modifiers": [...] } } }
// Output: { topic: "X", subtopic: "Y", keywords: [...], style_modifiers: [...] }
print('\n--- Transforming and inserting data ---');

const documents = [];
let categoryCount = 0;
let subjectCount = 0;

for (const [category, subjects] of Object.entries(data)) {
    categoryCount++;
    print(`\nCategory: ${category}`);
    
    for (const [subject, content] of Object.entries(subjects)) {
        subjectCount++;
        
        if (content.keywords && Array.isArray(content.keywords)) {
            const doc = {
                topic: category,                 // Backend uses 'topic' field
                subtopic: subject,               // Backend uses 'subtopic' field
                keywords: content.keywords,
                style_modifiers: content.style_modifiers || [],
                created_at: new Date(),
                updated_at: new Date()
            };
            
            documents.push(doc);
            print(`  - ${subject}: ${content.keywords.length} keywords, ${doc.style_modifiers.length} style_modifiers`);
        }
    }
}

print(`\n--- Inserting ${documents.length} documents ---`);

if (documents.length === 0) {
    print('ERROR: No documents to insert!');
    quit(1);
}

try {
    const insertResult = db.quiz_data.insertMany(documents);
    print(`✓ Successfully inserted ${Object.keys(insertResult.insertedIds).length} documents`);
} catch (e) {
    print('ERROR: Failed to insert documents: ' + e.message);
    quit(1);
}

// Create indexes for better query performance
print('\n--- Creating indexes ---');
try {
    db.quiz_data.createIndex({ topic: 1 });
    db.quiz_data.createIndex({ subtopic: 1 });
    db.quiz_data.createIndex({ topic: 1, subtopic: 1 });
    print('✓ Indexes created successfully');
} catch (e) {
    print('WARNING: Failed to create indexes: ' + e.message);
    // Continue anyway, indexes are optional
}

// Verify the data
print('\n=== Verification ===');
const finalCount = db.quiz_data.countDocuments();
print(`Total documents: ${finalCount}`);
print(`Total categories: ${categoryCount}`);
print(`Total subjects: ${subjectCount}`);

print('\nCategories in database:');
const categories = db.quiz_data.distinct('topic');
categories.forEach(cat => {
    const count = db.quiz_data.countDocuments({ topic: cat });
    print(`  - ${cat}: ${count} subjects`);
});

// Show a sample document
print('\nSample document:');
const sample = db.quiz_data.findOne();
if (sample) {
    print('  topic: ' + sample.topic);
    print('  subtopic: ' + sample.subtopic);
    print('  keywords: ' + sample.keywords.length + ' items');
    print('  style_modifiers: ' + sample.style_modifiers.length + ' items');
}

print('\n=== Database Initialization Complete! ===');
quit(0);
